import asyncio
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

import fractale.engines.native.result as results
from fractale.logger.logger import logger

from .helper_agent import HelperAgent

manager_prompt = f"""You are a planner agent. Your goal is to interactively work with a user to derive a plan. A plan is a sequence of steps. Each step has a name, and can be a call to a tool or prompt endpoint. You should look at the tools and prompts you have access to. Inspect the goals of the user, and write a plan. The plan MUST be a json list, where each item has a type (tool or agent) and a set of inputs (key value pairs). If an input is an agent, it MUST have a "prompt" that corresponds to a server prompt endpoint. For a server prompt endpoint, please use "inputs" to define arguemnts for the prompt generation. If you request an agent with a prompt endpoint, you can assume the agent will be able to call the same tools that you see. You should only call tools if there is a clear, logical step that should happen without agentic thinking. A tool MUST minimally have the structure {{"name": "<name>", "tool": "<tool_call>", "type": "tool"}} with the "name" of your choosing and the name of the call under "tool." If the function call has arguments, put those as key value pairs under "inputs." There is NO interactive user input after our interaction here, and you CANNOT define a custom prompt for a step, so you must carefully define your entire plan now. You MUST come up with a list of steps (agent types that use prompts and tool types) that can run an entire orchestration. For now, you MUST define all inputs. Inputs CAN use Jinja2 syntax to reference inputs and outputs from other steps, eg.., {{{{steps.<step_name>.<inputs|outputs>.<key_name>}}}}. When possible and known, you MUST make an effort to use strings/numbers directly as input values. You cannot reference outputs for a step that has not been run yet.
For each step, you can optionally define a "transitions" key that is also a dictionary with (also optional) "success" and "failure." Upon success or failure, the state machine will transition to the step that matches the name of the string that you provide. If you are CERTAIN about the output structure of a step (from the tool) you CAN define another top level key "rules" that is also a dictionary, and within the dictionary keys that correspond to "failure" and/or "success." Each of those is a list, where each item in the list is to be evaluated against the code result returned by the tool or agent to trigger the condition. We use the library on pypi boolia.
The first step in your list will be run first by default. For subsequent steps, you MUST include them in a transition somewhere to be included in the state machine. You MUST do your best to define transitions, when possible.

Here is the user goal: %s

You MUST come up with a plan. If you want to prompt the user for more information or ask a question, respond with a json structure with "prompt" and we will return the answer. You can add "options" to the "prompt" if you want to limit the user to a set of choices, and "default" to set a default choice. You MUST inspect the environment (resources, data) and have confidence about what you are going to run before you return the final plan. When you have enough information to run the plan, return it as a list of steps under a "steps" key in the format requested."""


def get_user_input(
    message: str, options: Optional[List[str]] = None, default: Optional[str] = None
) -> str:
    """
    Asks the user for input. If options are provided, uses numbered selection.
    Recursively asks again if the user provides an empty response without a default.
    """
    console = Console()

    def try_again(answer, message, options, default):
        """
        Determine if we need to try again (or just return answer)
        """
        if answer is None or (isinstance(answer, str) and answer.strip() == ""):
            console.print("[italic red]Input cannot be empty. Please try again.[/italic red]")
            return get_user_input(message, options, default)
        return answer

    if options:

        # Always allow the user to ask for something else
        options.append("Something else")

        # 1. Create mapping: "1" -> "Option Text"
        numbered_map = {str(i): opt for i, opt in enumerate(options, 1)}

        # 2. Build display string
        numbered_choices_str = "\n".join(
            f"[bold cyan]{num}[/bold cyan]. {text}" for num, text in numbered_map.items()
        )

        console.print(
            Panel(
                f"{message}\n\n{numbered_choices_str}",
                title="[bold violet]Input Requested[/bold violet]",
                expand=False,
            )
        )

        # 3. If the default is the text of an option, find its number
        default_num = None
        if default:
            for num, text in numbered_map.items():
                if text == default:
                    default_num = num
                    break

        # 4. Prompt for number
        choice_key = Prompt.ask(
            "[bold yellow]Select a number[/bold yellow]",
            choices=list(numbered_map.keys()),
            default=default_num,
        )

        # Recursive check (though rich.Prompt usually forces a choice if 'choices' is set)
        if not choice_key:
            return get_user_input(message, options, default)

        choice = numbered_map[choice_key]

        # If we have the "something else" response:
        if choice == len(numbered_map) - 1:
            answer = Prompt.ask(f"[bold violet]{message}[/bold violet]", default=default)
            return try_again(answer, message, options, default)
        return numbered_map[choice_key]

    else:
        answer = Prompt.ask(f"[bold violet]{message}[/bold violet]", default=default)

        # If user pressed Enter and there was no default
        return try_again(answer, message, options, default)


class ManagerAgent(HelperAgent):
    """
    Interact with the user to derive a plan.
    """

    agent_result_truncate = 1000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prompt_map = {}
        self.tool_map = {}

    async def run_loop(self, step, **kwargs):
        """
        Perform the debug task and return a Helper agent response
        """
        await self.set_lookup_maps()
        prompt = manager_prompt % step.instruction

        # Hide the larger instruction from the user
        logger.panel(step.instruction, title="Agent Request", color="green")

        while True:
            # 1. Await the agent response so the loop can process other tasks
            result = self.ask(prompt, use_tools=True, memory=True)

            if not result.calls:
                result = results.parse_response(result.content, result.metrics)
                if result.data and "steps" in result.data:
                    # Set schemas for steps
                    result.data["steps"] = self.set_step_maps(result.data["steps"])
                    return result

                # If we have a prompt, it will be shown here
                elif result.data and "prompt" in result.data:
                    prompt = await self.ask_user(
                        prompt=result.data["prompt"],
                        options=result.data.get("options"),
                        default=result.data.get("default"),
                    )
                    logger.panel(prompt, title="User Answer")
                    prompt = manager_prompt % step.instruction + " " + prompt

                # prompt the user with whatever the LLM is presenting

                else:
                    prompt = await self.ask_user(result.content)
                    logger.panel(prompt, title="User Answer")
                    prompt = manager_prompt % step.instruction + " " + prompt

            else:
                tool_calls = []
                async with self.client:
                    for call in result.calls:
                        result_tool = await self.call_tool(call)
                        if result_tool is not None:
                            tool_calls.append(result_tool.content)

                prompt = "Here are the results from your calls:" + "\n".join(tool_calls)

    async def ask_user(self, prompt, options=None, default=None):
        """
        Ask the user to respond to a question without blocking the event loop.
        """
        # asyncio.to_thread allows the blocking rich.prompt to run in a background thread
        return await asyncio.to_thread(get_user_input, prompt, options, default)

    def set_step_maps(self, steps):
        """
        Set maps for steps. Right now we raise errors if tools/prompts are missing or incorrectly
        selected. We only add steps that are explicitly tool or prompt, because the agent often adds
        intermediate steps it does here.
        """
        new_steps = []
        for step in steps:
            if "prompt" in step:
                if step["prompt"] not in self.prompt_map:
                    raise ValueError("Agent requested prompt that does not exist")
                step["schema"] = self.prompt_map.get(step["prompt"])
                new_steps.append(step)
            elif "tool" in step:
                if step["tool"] not in self.tool_map:
                    raise ValueError("Agent requested tool that does not exist")
                step["schema"] = self.tool_map.get(step["tool"])
                # Force the type to be tool, we don't have a use case for it to not be
                step["type"] = "tool"
                new_steps.append(step)
        return new_steps

    async def set_lookup_maps(self):
        """
        Get lookup maps for tool and prompt schemas for steps

        Important: this assumes a server with calls that do not change. If the functions
        will change, this needs to be called on demand.
        """
        async with self.client:
            prompts = await self.client.list_prompts()
            p_list = prompts.prompts if hasattr(prompts, "prompts") else prompts
            self.prompt_map = {p.name: p.model_dump() for p in p_list}

            tools = await self.client.list_tools()
            t_list = tools.tools if hasattr(tools, "tools") else tools
            self.tool_map = {t.name: t.model_dump() for t in t_list}
