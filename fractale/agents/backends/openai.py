import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

from openai import OpenAI

from fractale.core.config import ModelConfig
from fractale.db import get_database

from .backend import LLMBackend

default_model = "gpt-5-mini"


class OpenAIBackend(LLMBackend):
    def __init__(self, config: ModelConfig = None, tools=None):
        super().__init__()
        self.api_key = getattr(config, "api_key", None) or os.getenv("OPENAI_API_KEY")
        self.base_url = getattr(config, "base_url", None) or os.getenv("OPENAI_BASE_URL")
        self.model_name = (
            getattr(config, "model_name", None) or os.environ.get("OPENAI_MODEL") or default_model
        )
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set.")

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        self.tools = tools
        self._history = []
        self.database = get_database()

    async def list_tools(self):
        """
        Fetch and convert MCP tools to OpenAI function format.
        """
        async with self.mcp_client as client:
            result = await client.list_tools()
            mcp_tools = result.tools if hasattr(result, "tools") else result
            openai_tools = []
            for t in mcp_tools:
                openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description or "",
                            "parameters": t.inputSchema,
                        },
                    }
                )
            return openai_tools

    def _run_async(self, coro):
        """
        Helper to run a coroutine from a sync function,
        even if an event loop is already running in the current thread.
        """
        try:
            # If no loop is running, we can just use asyncio.run
            asyncio.get_running_loop()
            # If we are here, a loop IS running.
            # We must run the coroutine in a separate thread to avoid blocking/conflicts.
            with ThreadPoolExecutor() as executor:
                return executor.submit(asyncio.run, coro).result()
        except RuntimeError:
            # No loop running, standard execution
            return asyncio.run(coro)

    def generate_response(
        self,
        prompt: str = None,
        use_tools: bool = True,
        memory: bool = False,
        tools: List[str] = None,
    ) -> Tuple[str, Any, List[Dict]]:
        """
        Generate response synchronously. NO AWAIT REQUIRED.
        """
        active_tools = None
        if use_tools:
            # Use the helper to resolve the async tool discovery synchronously
            if not self.tools:
                self.tools = self._run_async(self.list_tools())

            if tools:
                active_tools = [t for t in self.tools if t["function"]["name"] in tools]
            else:
                active_tools = self.tools

        # Manage memory history
        if not memory:
            messages = [{"role": "user", "content": prompt}]
        else:
            self._history.append({"role": "user", "content": prompt})
            messages = self._history

        # API Call is natively synchronous in the OpenAI library
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            tools=active_tools if active_tools else None,
            tool_choice="auto" if active_tools else None,
        )

        # Parse Result
        choice = response.choices[0]
        content = choice.message.content or ""

        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(
                    {"name": tc.function.name, "args": json.loads(tc.function.arguments)}
                )

        if memory:
            self._history.append(choice.message)

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        self.database.record_metric(
            {
                "use_tools": use_tools,
                "metrics": usage,
                "memory": memory,
                "tools": tools,
                "prompt": prompt,
            }
        )
        return content, tool_calls
