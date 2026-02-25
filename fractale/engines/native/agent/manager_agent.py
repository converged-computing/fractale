import asyncio
import json

import fractale.core.result as results
import fractale.utils as utils
from fractale.core.plan.validate import StepsValidator
from fractale.logger.logger import logger

from .helper_agent import HelperAgent

manager_prompt = f"""You are a planner agent. Your task is to inspect the goals of the user, and write a plan. The plan MUST be a json list, where each item has a type "tool" or "agent" or "prompt" and a set of inputs (key value pairs). You should look at the tools and prompts you have access to. Here are instructions for each step "type":

prompt:
type "prompt" is a call to a prompt endpoint, it MUST have a "prompt" that corresponds to the prompt endpoint name. A prompt will generate a prompt and then allow the LLM to respond to subsequent calls, with access to the same tools that you see. You should use "inputs" to define arguments for the prompt generation.

tool:
type "tool" corresponds to a tool endpoint. You should call tools if there is a clear, logical step that should happen without agentic thinking. A tool MUST minimally have the structure {{"name": "<name>", "tool": "<tool_call>", "type": "tool"}}. Arguments are key value pairs under "inputs."

agent:
A tool with an annotation for "fractale.type: agent" indicates an "agent" type call. An agent will orchestrate a scoped task, and have access to the same tool endpoints that you see. You should try to maximize use of agents, and derive a plan with fewer steps. A general prompt agent exists for generalized tasks, and should be used sparingly.

Instructions
1. DISCOVER tools and prompts available to you.
2. EXPLORE resources available to you and information provided by tools
3. CAPTURE information to derive steps for the state machine, a combination of agents, tool calls, and prompts.
4. WRITE clear goals and tasks for sub agents that are specific to each task in the state machine.
5. DEFINE "transitions" between steps and "rules" to guide them.

The "transitions" key of a step is a dictionary with "success" and "failure." Upon success or failure, the state machine will transition to the step that matches the name of the string that you provide.
The "rules." You should choose simplicity in your plan and aim for fewer steps.

You should make tools calls on your own to maximally discover resources to guide the sub agents. You MUST come up with a list of steps that can run an entire orchestration. For now, you MUST define all inputs. Inputs CAN use Jinja2 syntax to reference inputs and outputs from other steps, eg.., {{{{steps.<step_name>.<inputs|outputs>.<key_name>}}}}. When possible and known, you MUST make an effort to use strings/numbers directly as input values. You cannot reference outputs for a step that has not been run yet.
If you are CERTAIN about the output structure of a step you CAN define another step key "rules" that is also a dictionary, and within the dictionary the keys MUST correspond to "failure" and/or "success." Each entry in the dictionary MUST be a list of strings to be evaluated against the code result returned by the tool or agent to trigger the condition. We use the library on pypi boolia. Here are examples.

{{"failure": ["not valid"]}}  "Fail is the valid key in the dictionary is set to False"
{{"success": ["valid"]}}  "Succeed if the valid key in the dictionary is set to True
{{"success": ["house.light.on"]}} "Succeed if this structure: {{"house": {{"light": {{"on": True}}}}}}"
{{"failure": ["user.age >= 18 and 'ops' in user.roles"]}} "Fail {{"user": {{"age": 21, "roles": ["admin", "ops"]}}}}"

The first step in your list will be run first by default. For subsequent steps, you MUST include them in a transition somewhere to be included in the state machine. You MUST do your best to define transitions, when possible. You MUST do your best to define rules, when possible. If there is a request that is stateful, you can use a strategy of creating a rule to retry on failure.
If you are missing information or a tool, you MUST ask or tell the user what you need during planning.

Here is the user goal: %s

You MUST come up with a plan. If you want to prompt the user for more information or ask a question, respond with a json structure with "prompt" and we will return the answer. You can add "options" to the "prompt" if you want to limit the user to a set of choices, and "default" to set a default choice. You MUST inspect the environment (resources, data) and have confidence about what you are going to run before you return the final plan. When you have enough information to run the plan, return it as a list of steps under a "steps" key in the format requested."""


class ManagerAgent(HelperAgent):
    """
    Interact with the user to derive a plan.
    """

    agent_result_truncate = 1000

    async def run_loop(self, step, **kwargs):
        """
        Perform the debug task and return a Helper agent response
        """
        await self.set_lookup_maps()
        prompt = manager_prompt % step.instruction

        # Hide the larger instruction from the user
        logger.panel(step.instruction, title="Agent Request", color="green")

        while True:
            result = self.ask(prompt, use_tools=True, memory=True)

            if not result.calls:
                result = results.parse_response(result.content, result.metrics)

                # We need to make sure we have steps, and they are not empty
                if result.data and "steps" in result.data and result.data["steps"]:
                    errors = StepsValidator(result.data["steps"]).validate()
                    if errors:
                        prompt = f"Your plan needs work:\n{errors}"
                        continue

                    # Check with user that steps are ok (only yes or feedback)
                    preview = json.dumps(result.data["steps"], indent=4)
                    is_ok = await self.ask_validate_user(
                        f"Is this plan OK?\n```json\n{preview}\n```\n",
                        choices=["yes", "y", "feedback", "f"],
                    )

                    # First we need to validate the steps
                    if is_ok == "yes":

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

    def set_step_maps(self, steps):
        """
        Set maps for steps. All prompts/tools should be known (checked by validate_steps above).
        """
        new_steps = []
        for step in steps:
            agent_call = step.get("tool") or step.get("agent")
            if "prompt" in step:
                step["schema"] = self.prompt_map.get(step["prompt"])
                new_steps.append(step)
            # This is a fractale agent
            elif "agent" in step and agent_call in self.tool_map:
                step["schema"] = self.tool_map.get(agent_call)
                step["type"] = "agent"
                new_steps.append(step)
            elif "tool" in step:
                step["schema"] = self.tool_map.get(step["tool"])
                # Force the type to be tool, we don't have a use case for it to not be
                step["type"] = "tool"
                new_steps.append(step)
        return new_steps
