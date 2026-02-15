import asyncio
import os
from typing import Any, Dict, List, Tuple

from fractale.core.config import ModelConfig

from .base import LLMBackend

default_model = "gemini-2.5-pro"


class GeminiBackend(LLMBackend):
    def __init__(self, config: ModelConfig = None, tools=None):
        """
        export GEMINI_API_KEY=xxxx
        from fractale.engines.native.backends.gemini import GeminiBackend
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

    async def list_tools(self):
        async with self.mcp_client:
            return await self.mcp_client.list_tools()

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

    @property
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
            for part in candidate.content.parts:
                if part.text:
                    text_content += part.text

                if part.function_call:
                    tool_calls.append(
                        {"name": part.function_call.name, "args": part.function_call.args}
                    )

        return tool_calls

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
            calls = self.generate_tool_calls(response.candidates)
        elif use_tools and not response.candidates:
            return "Error: Blocked by safety filters or empty response", None, []

        usage = {}
        if response.usage_metadata:
            usage = {}
            for k, v in response.usage_metadata.model_dump().items():
                if v is not None and isinstance(v, int):
                    usage[k] = v

        # I noticed we get a warning by returning response.text when we have
        # tool calls. So we extract text parts to avoid the SDK warning
        text_parts = []
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.text:
                    text_parts.append(part.text)
            final_text = "".join(text_parts)
        else:
            print("RESPONSE")
            print(dir(response))
            final_text = response.text

        return final_text, usage, calls
