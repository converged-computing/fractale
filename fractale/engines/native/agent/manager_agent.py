import asyncio
import json
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

import fractale.engines.native.result as results
from fractale.logger.logger import logger

from .helper_agent import HelperAgent

manager_prompt = f"""You are a planner agent. Your goal is to interactively work with a user to derive a plan.
A plan is a sequence of steps. Each step has a name, and can be a call to a tool or prompt endpoint. You should do the following:

1. Look at the tools and prompts you have access to.
2. Inspect the goals of the user, and write a plan. The plan MUST be a json list, where each item has a type (tool or agent) and a set of inputs (key value pairs).
3. If an input is an agent, it MUST have a prompt for an agent to respond to.

For most of the plan, you should assume the agent will be calling tools, but provide guidance for how you think it should be done.
You should only call tools if there is a clear, logical step that should happen without agentic thinking.
Here is the user goal:

%s

You MUST come up with a plan. If you want to prompt the user for more information or ask a question, respond with a json structure with "prompt" and we will
return the answer. You can add "options" to the "prompt" if you want to limit the user to a set of choices, and "default" to set a default choice.
When you have enough information to run the plan, return it as a list of steps under a "steps" key in the format requested.
"""


def get_user_input(
    message: str, options: Optional[List[str]] = None, default: Optional[str] = None
) -> str:
    """
    Asks the user for a prompt. If options are provided,
    validates that the user selects one.
    """
    console = Console()

    if options:
        # Create a formatted list of choices for the user to see
        choices_str = ", ".join(f"[bold cyan]{opt}[/bold cyan]" for opt in options)
        console.print(
            Panel(f"{message}\n\n[bold white]Choices:[/bold white] {choices_str}", expand=False)
        )

        # Prompt.ask handles the validation loop automatically when choices are provided
        answer = Prompt.ask(
            "[bold yellow]Select an option\n[/bold yellow]", choices=options, default=default
        )
    else:
        # Standard free-text prompt
        answer = Prompt.ask(f"[bold violet]{message}\n[/bold violet]", default=default)

    # Require an answer
    if not answer:
        return get_user_input(message, options, default)
    return answer


class ManagerAgent(HelperAgent):
    """
    Interact with the user to derive a plan.
    """

    async def run_loop(self, step):
        """
        Perform the debug task and return a Helper agent response
        """
        prompt = manager_prompt % step.instruction

        while True:
            # 1. Await the agent response so the loop can process other tasks
            result = self.ask(prompt, use_tools=True, memory=True)

            if not result.calls:
                result = results.parse_response(result.content, result.metrics)
                if result.data and "steps" in result.data:
                    logger.panel(result.content, title="Agent Response", color="blue")
                    return result.data["steps"]

                # If we have a prompt, it will be shown here
                elif result.data and "prompt" in result.data:
                    answer = await self.ask_user(
                        prompt=result.data["prompt"],
                        options=result.data.get("options"),
                        default=result.data.get("default"),
                    )

                # prompt the user with whatever the LLM is presenting

                else:
                    answer = await self.ask_user(result.content)
                prompt = f"Here is the information you requested:\n {answer}"
                logger.panel(prompt, title="User Answer")

            else:
                tool_calls = []
                async with self.client:
                    for call in result.calls:
                        result_tool = await self.call_tool(call)
                        if result_tool is not None:
                            print(result_tool)
                            tool_calls.append(result_tool.content)

                prompt = "Here are the results from your calls:" + "\n".join(tool_calls)

    async def ask_user(self, prompt, options=None, default=None):
        """
        Ask the user to respond to a question without blocking the event loop.
        """
        # asyncio.to_thread allows the blocking rich.prompt to run in a background thread
        return await asyncio.to_thread(get_user_input, prompt, options, default)
