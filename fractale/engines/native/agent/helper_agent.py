# Native Engine Imports
from dataclasses import dataclass
from typing import List, Optional

from fractale.ui.adapters.cli import CLIAdapter

from .base_agent import StateMachineAgent


@dataclass
class HelperAgentResponse:
    """
    The respones from a helper agent
    """

    content: str
    calls: Optional[List] = None


debug_prompt = f"""PERSONA: You are a helper agent.
CONTEXT: We just ran a step and need help understanding an error here:
%s
GOAL: Debug the error, summarize it, and provide advise for fixing it.
"""


class HelperAgent(StateMachineAgent):
    """
    A simplified agent to make calls to a model.
    """

    def ask(self, prompt, use_tools=True, memory=True):
        """
        Ask the agent a question (assume we want memory)
        """
        from fractale.agents.base import backend

        response, calls = backend.generate_response(prompt, use_tools=use_tools, memory=memory)
        return HelperAgentResponse(response, calls)


class DebugAgent(HelperAgent):
    """
    The debug agent is given a scoped task to summarize and debug an error.
    """

    def debug(self, error):
        """
        Perform the debug task and return a Helper agent response
        """
        prompt = debug_prompt % error
        return self.ask(prompt, use_tools=False, memory=False)
