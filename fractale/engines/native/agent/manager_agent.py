import asyncio

import fractale.core.result as results
import fractale.utils as utils
from fractale.logger.logger import logger

from .helper_agent import HelperAgent

manager_prompt = f"""You are a planner agent. Your goal is to interactively work with a user to derive a plan. A plan is a sequence of steps. Each step has a name, and can be a call to a tool or prompt endpoint. You should look at the tools and prompts you have access to. Inspect the goals of the user, and write a plan. The plan MUST be a json list, where each item has a type (tool or agent) and a set of inputs (key value pairs). If an input is an agent, it MUST have a "prompt" that corresponds to a server prompt endpoint. For a server prompt endpoint, please use "inputs" to define arguemnts for the prompt generation. If you request an agent with a prompt endpoint, you can assume the agent will be able to call the same tools that you see. You should only call tools if there is a clear, logical step that should happen without agentic thinking. A tool MUST minimally have the structure {{"name": "<name>", "tool": "<tool_call>", "type": "tool"}} with the "name" of your choosing and the name of the call under "tool." If the function call has arguments, put those as key value pairs under "inputs." There is NO interactive user input after our interaction here, and you CANNOT define a custom prompt for a step, so you must carefully define your entire plan now. You MUST come up with a list of steps (agent types that use prompts and tool types) that can run an entire orchestration. For now, you MUST define all inputs. Inputs CAN use Jinja2 syntax to reference inputs and outputs from other steps, eg.., {{{{steps.<step_name>.<inputs|outputs>.<key_name>}}}}. When possible and known, you MUST make an effort to use strings/numbers directly as input values. You cannot reference outputs for a step that has not been run yet.
For each step, you can optionally define a "transitions" key that is also a dictionary with (also optional) "success" and "failure." Upon success or failure, the state machine will transition to the step that matches the name of the string that you provide. If you are CERTAIN about the output structure of a step (from the tool) you CAN define another top level key "rules" that is also a dictionar, and within the dictionary the keys MUST correspond to "failure" and/or "success." Each entry in the dictionary MUST be a list of strings to be evaluated against the code result returned by the tool or agent to trigger the condition. We use the library on pypi boolia.
The first step in your list will be run first by default. For subsequent steps, you MUST include them in a transition somewhere to be included in the state machine. You MUST do your best to define transitions, when possible.

Here is the user goal: %s

You MUST come up with a plan. If you want to prompt the user for more information or ask a question, respond with a json structure with "prompt" and we will return the answer. You can add "options" to the "prompt" if you want to limit the user to a set of choices, and "default" to set a default choice. You MUST inspect the environment (resources, data) and have confidence about what you are going to run before you return the final plan. When you have enough information to run the plan, return it as a list of steps under a "steps" key in the format requested."""


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
                # We need to make sure we have steps, and they are not empty
                if result.data and "steps" in result.data and result.data["steps"]:
                    # Check with user that steps are ok (only yes or feedback)
                    is_ok = await self.ask_validate_user(
                        f"Is this plan OK?\n```python\n{result.data['steps']}\n```\n",
                        choices=["y", "yes", "feedback", "f"],
                    )
                    if is_ok == "yes":

                        # First we need to validate the steps
                        errors = self.validate_steps(result.data["steps"])
                        if errors:
                            prompt = f"Your plan needs work:\n{errors}"
                            continue

                        # Set schemas for steps
                        result.data["steps"] = self.set_step_maps(result.data["steps"])
                        return result
                    prompt = f"Your plan needs work:\n{is_ok}"

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
                async with self.mcp_client:
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
        return await asyncio.to_thread(utils.get_user_input, prompt, options, default)

    async def ask_validate_user(
        self, message, options=None, default=None, choices=None, is_markdown=True
    ):
        """
        Ask the user to respond to a question without blocking the event loop.
        """
        # asyncio.to_thread allows the blocking rich.prompt to run in a background thread
        return await asyncio.to_thread(
            utils.get_user_validation,
            message,
            options,
            default,
            choices=choices,
            is_markdown=is_markdown,
        )

    def validate_steps(self, steps):
        """
        Ensure that the agent does not request a tool or prompt that does not exist.
        """
        errors = []
        for step in steps:
            if "prompt" in step:
                if step["prompt"] not in self.prompt_map:
                    errors.append(f"Agent requested prompt that does not exist: {step['prompt']}")
            elif "tool" in step:
                if step["tool"] not in self.tool_map:
                    errors.append(f"Agent requested tool that does not exist: {step['tool']}")
        if errors:
            return "\n".join(errors)

    def set_step_maps(self, steps):
        """
        Set maps for steps. All prompts/tools should be known (checked by validate_steps above).
        """
        new_steps = []
        for step in steps:
            if "prompt" in step:
                step["schema"] = self.prompt_map.get(step["prompt"])
                new_steps.append(step)
            elif "tool" in step:
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
        async with self.mcp_client:
            prompts = await self.mcp_client.list_prompts()
            p_list = prompts.prompts if hasattr(prompts, "prompts") else prompts
            self.prompt_map = {p.name: p.model_dump() for p in p_list}

            tools = await self.mcp_client.list_tools()
            t_list = tools.tools if hasattr(tools, "tools") else tools
            self.tool_map = {t.name: t.model_dump() for t in t_list}
