from abc import ABC, abstractmethod

from fractale.agents.base import AgentBase


class LLMBackend(AgentBase, ABC):
    """
    Abstract interface for any LLM provider (Gemini, OpenAI, Llama, Local).
    """

    def __init__(self):
        # Init mcp client
        self.init()

        # Chat is init for cases when we want to use memory
        self._chat_all_tools = None
        self._chat_no_tools = None
        self._chat_with_tools = None

    @abstractmethod
    def generate_response(self, *args, **kwargs):
        """
        Returns a tuple: (text_content, reasoning_content, tool_calls)
        """
        pass
