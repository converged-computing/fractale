import asyncio
import time

import fractale.core.result as results
from fractale.agents import AgentBase


class StateMachineAgent(AgentBase):
    """
    A state machine agent base is an agent with a run function intended
    for a state machine.
    """

    agent_result_truncate = 800

    def reset(self, plan=None):
        """
        Reset the agent. Be careful if your model client is saving state here.
        """
        if plan is not None:
            self.plan = plan

    def run(self, *args, **kwargs):
        """
        Main entry point called by the Manager.

        run -> run_loop (prompt) -> process_loop (inner loop)
        """
        show_result = kwargs.get("show_result", True)

        try:
            result = asyncio.run(self.run_loop(*args, **kwargs))
        except Exception as e:
            result = results.StepResult(str(e))

        if show_result:
            result.show(truncate=self.agent_result_truncate)
        return result
