import json
import os
from typing import Any, Dict, List, Tuple

from fractale.core.config import ModelConfig

from .backend import LLMBackend

# IMPORTANT: this file is not currently used/functioning. It needs to be written.


class LlamaBackend(LLMBackend):
    """
    Backend for Meta Llama 3.1+ models via OpenAI-Compatible endpoints (Ollama, Groq, vLLM).
    """

    def __init__(self, config: ModelConfig):
        super().__init__()

        # Use config for connection, fallback to defaults for local Ollama
        base_url = config.base_url or "http://localhost:11434/v1"
        api_key = config.api_key or "ollama"

        import openai

        self.client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.model_name = config.model_name or "llama3.1"

        self.disable_history = os.environ.get("LLAMA_DISABLE_HISTORY") is not None
        self.history = []
        self.tools_schema = []
        self._usage = {}

    async def initialize(self, mcp_tools: List[Any]):
        """
        Llama 3.1 follows the OpenAI Tool Schema standard.
        """
        self.tools_schema = []
        for tool in mcp_tools:
            self.tools_schema.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                }
            )

    def generate_response(
        self,
        prompt: str = None,
        tool_outputs: List[Dict] = None,
        use_tools: bool = True,
        one_off: bool = False,
        tools: List[str] = None,
    ) -> Tuple[str, str, List[Dict]]:
        """
        Manage history and call Llama.
        """
        # TODO: Implement one_off support

        if prompt:
            self.history.append({"role": "user", "content": prompt})

        if tool_outputs and use_tools and not self.disable_history:
            for out in tool_outputs:
                # Ensure name matches the sanitized version sent to LLM
                llm_name = out["name"].replace("-", "_")
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": out["id"],
                        "name": llm_name,
                        "content": str(out["content"]),
                    }
                )

        api_tools = self.tools_schema if self.tools_schema else None
        tool_choice = "auto" if api_tools else None

        if not use_tools:
            api_tools = None
            tool_choice = None
        elif tools:
            # 1. Sanitize requested names (docker-build -> docker_build)
            target_names = [t.replace("-", "_") for t in tools if t]

            # 2. Filter the schema list
            api_tools = [t for t in self.tools_schema if t["function"]["name"] in target_names]

            # 3. Determine forcing strategy
            if len(target_names) == 1:
                # Force specific function
                tool_choice = {"type": "function", "function": {"name": target_names[0]}}
            else:
                # Force any function from the filtered list
                tool_choice = "required"

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=self.history,
                tools=api_tools,
                tool_choice=tool_choice,
            )
        except Exception as e:
            return f"LLAMA API ERROR: {str(e)}", "", []

        print(f"Response {response}")
        msg = response.choices[0].message

        if response.usage:
            self._usage = dict(response.usage)

        if not self.disable_history:
            self.history.append(msg)

        text_content = msg.content or ""

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,  # This will be underscored (docker_build)
                        "args": json.loads(tc.function.arguments),
                    }
                )

        return text_content, getattr(msg, "reasoning_content", ""), tool_calls

    @property
    def token_usage(self):
        return self._usage
