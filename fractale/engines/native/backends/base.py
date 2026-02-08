import os
from abc import ABC, abstractmethod

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


class LLMBackend(ABC):
    """
    Abstract interface for any LLM provider (Gemini, OpenAI, Llama, Local).
    """

    def __init__(self):
        self.init_mcp()

        # Chat is init for cases when we want to use memory
        self._chat_all_tools = None
        self._chat_no_tools = None
        self._chat_with_tools = None

    def init_mcp(self):
        """
        Setup the mcp client for the state machine. We use
        the streaming http transport from fastmcp.
        """
        port = os.environ.get("FRACTALE_MCP_PORT", "8089")
        token = os.environ.get("FRACTALE_MCP_TOKEN")
        url = f"http://127.0.0.1:{port}/mcp"

        headers = {"Authorization": token} if token else None
        transport = StreamableHttpTransport(url=url, headers=headers)
        self.mcp_client = Client(transport)

    @abstractmethod
    def generate_response(self, *args, **kwargs):
        """
        Returns a tuple: (text_content, reasoning_content, tool_calls)
        """
        pass
