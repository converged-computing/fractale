import asyncio
import functools
import logging
import os
import random
import time
from typing import Any, Dict, List, Tuple

from google.genai.errors import ClientError, ServerError

from fractale.core.config import ModelConfig
from fractale.db import get_database

from .backend import LLMBackend

default_model = "gemini-2.5-pro"

logger = logging.getLogger(__name__)


def retry_gemini(max_retries: int = 5, base_delay: float = 1.0, max_delay: float = 60.0):
    """
    Decorator for retrying Gemini API calls with exponential backoff and jitter.
    Errors we should retry are 503 (Service Unavailable), 429 (too many requests),
    500 (Internal Server error), 502 (Bad Gateway) and 504 (Gateway Timeout).

    Args:
        max_retries: Maximum number of attempts.
        base_delay: Starting delay in seconds.
        max_delay: Maximum cap for the delay.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except (ServerError, ClientError) as e:
                    # Extract status code
                    status_code = getattr(e, "code", None) or getattr(e, "status_code", None)
                    retryable_codes = [429, 500, 502, 503, 504]

                    if status_code in retryable_codes and retries < max_retries:
                        retries += 1
                        # Exponential backoff: base * 2^n
                        delay = min(base_delay * (2**retries), max_delay)
                        # Add jitter: +/- 25% of the delay
                        jitter = delay * 0.25 * (2 * random.random() - 1)
                        sleep_time = max(0, delay + jitter)
                        logger.warning(
                            f"Gemini {status_code} error. Retrying in {sleep_time:.2f}s "
                            f"(Attempt {retries}/{max_retries})..."
                        )
                        time.sleep(sleep_time)
                    # Not candidate for retry or we hit max attempts
                    else:
                        raise e

        return wrapper

    return decorator


class GeminiBackend(LLMBackend):
    def __init__(self, config: ModelConfig = None, tools=None):
        """
        export GEMINI_API_KEY=xxxx
        from fractale.agents.backends.gemini import GeminiBackend
        backend = GeminiBackend()
        """
        super().__init__()
        from google import genai
        from google.genai import types

        self.genai = genai
        self.types = types

        self.api_key = getattr(config, "api_key", None) or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set.")

        self.model_name = getattr(config, "model_name", None) or default_model
        self.client = self.genai.Client(api_key=self.api_key)

        # Allow custom set of tools to be set on init
        self.tools = tools
        if not self.tools:
            self.tools = asyncio.run(self.list_tools())
        self.database = get_database()

    # Configs with different levels of tool allowances
    @property
    def all_tools_config(self):
        return self.types.GenerateContentConfig(tools=self.tools)

    @property
    def no_tools_config(self):
        tool_config = self.types.ToolConfig(
            function_calling_config=self.types.FunctionCallingConfig(mode="NONE")
        )
        return self.types.GenerateContentConfig(tools=[], tool_config=tool_config)

    def some_tools_config(self, tools):
        tool_config = self.types.ToolConfig(
            function_calling_config=self.types.FunctionCallingConfig(
                mode="ANY", allowed_function_names=tools
            )
        )
        return self.types.GenerateContentConfig(tools=[tools], tool_config=tool_config)

    @property
    def chat_all_tools(self):
        """
        Use chat for some semblance of memory
        """
        if self._chat_all_tools is not None:
            return self._chat_all_tools
        self._chat_all_tools = self.client.chats.create(
            model=self.model_name, config=self.all_tools_config
        )
        return self._chat_all_tools

    @property
    def chat_no_tools(self):
        """
        Use chat for some semblance of memory, but no tools
        """
        if self._chat_no_tools is not None:
            return self._chat_no_tools
        self._chat_no_tools = self.client.chats.create(
            model=self.model_name, config=self.no_tools_config
        )
        return self._chat_no_tools

    def chat_some_tools(self, tools):
        """
        Use chat for some semblance of memory WITH specific tools

        Once this is created, the tools are set.
        """
        if self._chat_with_tools is not None:
            return self._chat_with_tools
        self._chat_with_tools = self.client.chats.create(
            model=self.model_name, config=self.some_tools_config(tools)
        )
        return self._chat_with_tools

    def generate_tool_calls(self, candidates):
        """
        Generate tool calling to return to calling agent.
        """
        tool_calls = []
        for candidate in candidates:
            text_content = ""
            tool_calls = []
            if not candidate.content.parts:
                continue
            for part in candidate.content.parts:
                if part.text:
                    text_content += part.text

                if part.function_call:
                    tool_calls.append(
                        {"name": part.function_call.name, "args": part.function_call.args}
                    )

        return tool_calls

    @retry_gemini(max_retries=5)
    def generate_response(
        self,
        prompt: str = None,
        use_tools: bool = True,
        memory: bool = False,
        tools: List[str] = None,
    ) -> Tuple[str, Any, List[Dict]]:
        """
        Generate response from Gemini using the new SDK patterns.
        """
        # One-off (no memory) call with any tools
        if not memory and use_tools and not tools:
            response = self.client.models.generate_content(
                model=self.model_name, contents=prompt, config=self.all_tools_config
            )

        # One-off, no tools
        elif not memory and not use_tools:
            response = self.client.models.generate_content(
                model=self.model_name, contents=prompt, config=self.no_tools_config
            )

        # One off, specific tools
        elif not memory and use_tools and tools is not None:
            response = self.client.models.generate_content(
                model=self.model_name, contents=prompt, config=self.some_tools_config(tools)
            )

        # We want to use specific tools with memory
        elif use_tools and tools and memory:
            response = self.chat_with_tools(tools).send_message(prompt)

        # We don't want tools, but we want a "memory" chat
        elif not use_tools and memory:
            response = self.chat_no_tools.send_message(prompt)

        # We want all tools with a memory chat
        elif memory:
            response = self.chat_all_tools.send_message(prompt)

        # Did we get tool calls?
        calls = []
        if response.candidates:

            # Did we get a malformed response?
            finish_reason = response.candidates[0].finish_reason
            if finish_reason.name == "MALFORMED_FUNCTION_CALL":
                print("⚠️ Malformed call detected. Cleaning output to retry...")
                cleaned_prompt = clean_output(prompt)
                return self.generate_response(
                    cleaned_prompt, use_tools=use_tools, memory=memory, tools=tools
                )

            calls = self.generate_tool_calls(response.candidates)
        elif use_tools and not response.candidates:
            return "Error: Blocked by safety filters or empty response", None, []

        usage = {}
        if response.usage_metadata:
            usage = {}
            for k, v in response.usage_metadata.model_dump().items():
                if v is not None and isinstance(v, int):
                    usage[k] = v
            self.database.record_metric(
                {
                    "use_tools": use_tools,
                    "metrics": usage,
                    "memory": memory,
                    "tools": tools,
                    "prompt": prompt,
                }
            )

        # I noticed we get a warning by returning response.text when we have
        # tool calls. So we extract text parts to avoid the SDK warning
        text_parts = []
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.text:
                    text_parts.append(part.text)
            final_text = "".join(text_parts)
        else:
            final_text = response.text

        # Google being flaky
        if "503 UNAVAILABLE" in final_text:
            print(final_text)
            time.sleep(300)
            return self.generate_response(prompt, use_tools, memory, tools)

        return final_text, calls


def clean_output(data: Any) -> str:
    """
    Try to handle characters that trigger malformed JSON responses
    without removing important content.
    """
    # Convert to string if it's a dict/list from tool_result.content
    text = str(data)
    text = text.replace("{", "❴").replace("}", "❵")
    text = text.replace("[", "❲").replace("]", "❳")
    text = text.replace('"', "'")
    text = text.replace("\\", "/")
    lines = text.splitlines()
    fenced = "\n".join([f"| {line}" for line in lines])
    return f"### RE-PROCESSED DATA (CLEANED FOR PARSING):\n{fenced}"
