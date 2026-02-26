import asyncio
import json

import fractale.core.result as results
import fractale.utils as utils
from fractale.core.plan.validate import StepsValidator
from fractale.logger.logger import logger

from .helper_agent import HelperAgent

boolia = f"""If you are CERTAIN about the output structure of a step from an output schema you MUST define "rules" that determine success or failure of the sub-agent. The "rules" is a dictionary, and within the dictionary the keys MUST correspond to "failure" and/or "success." Each entry in the dictionary MUST be a list of strings to be evaluated against the code result returned by the tool or agent to trigger the condition. We use the library on pypi boolia. Here are examples.

{{"failure": ["not valid"]}}  "Fail is the valid key in the dictionary is set to False"
{{"success": ["valid"]}}  "Succeed if the valid key in the dictionary is set to True
{{"success": ["house.light.on"]}} "Succeed if this structure: {{"house": {{"light": {{"on": True}}}}}}"
{{"failure": ["user.age >= 18 and 'ops' in user.roles"]}} "Fail {{"user": {{"age": 21, "roles": ["admin", "ops"]}}}}"
"""

# The step manager MUST generate just one step
manager_step_prompt = f"""You are a sub-agent planner. Your task is to inspect the goal of a user, and write a scoped prompt for a specific sub-agent. A sub-agent is ONE step in a state machine that corresponds to type "agent."

Instructions
1. DISCOVER tools available to you. A tool with an annotation for "fractale.type: agent" indicates an sub-agent type call.
2. UNDERSTAND the input needs of the sub-agent (tool) that the user is requesting to use. It is YOUR job to write an intelligent, scoped prompt to guide it.
3. EXPLORE resources, data, and information available to you by requesting tool calls. The output will be returned to you to decide how to act next.
4. WRITE a prompt for the sub-agent, and return as a SINGLE state machine step.

The sub-agent will orchestrate a scoped task, and have access to the same tool endpoints that you see. You should return a single step under a list, where the step has the structure {{"name": "<name>", "agent": "<agent_tool_endpoint_name>", "type": "agent"}}. Arguments are key value pairs under "inputs."
{boolia}

If you are missing information or a tool, you MUST ask the user for clarification.
Here is the user goal: %s

You MUST come up with a sub-agent prompt. To prompt the user for more information or ask a question, respond with a json structure with "prompt" and we will return the answer. You can add "options" to the "prompt" if you want to limit the user to a set of choices, and "default" to set a default choice. You MUST inspect the environment (resources, data) and have confidence about what you are going to run before you return the final single step list. It MUST be a single step list of steps under a "steps" key in the format requested.
"""

# The higher level manager makes an entire plan.
manager_prompt = f"""You are a planner agent. Your task is to inspect the goals of the user, and write a plan. The plan MUST be a json list, where each item has a type "agent" that coincides with a sub-agent that you can derive a specific prompt and inputs (key value pairs) for.

Instructions
1. DISCOVER tools and prompts available to you.
2. EXPLORE resources available to you and information by calling tools.
3. ASK questions to the user about information you cannot obtain.
4. CAPTURE specific goals and other needed inputs to call sub-agents and FORMAT into the input arguments for the sub-agent step.
5. DEFINE "transitions" between steps and "rules" to guide them.

The "transitions" key of a step is a dictionary with "success" and "failure." Upon success or failure, the state machine will transition to the step that matches the name of the string that you provide.
The "rules." You should choose simplicity in your plan and aim for fewer steps.

You ARE ONLY ALLOWED to call tool steps that are labeled as fractale.agent, an annotation in the tool.
You SHOULD make tool calls on your own to maximally discover resources to guide the sub agents. You MUST come up with a list of steps that can run an entire orchestration of sub-agents.
Inputs CAN use Jinja2 syntax to reference inputs and outputs from other steps, eg.., {{{{steps.<step_name>.<inputs|outputs>.<key_name>}}}}. When possible and known, you MUST make an effort to use strings/numbers directly as input values. You cannot reference outputs for a step that has not been run yet.
{boolia}

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

        # Default to plan type
        run_type = kwargs.get("run_type") or "plan"
        if run_type == "plan":
            prompt = manager_prompt % step.instruction
        else:
            prompt = manager_step_prompt % step.instruction

        # Hide the larger instruction from the user
        logger.panel(step.instruction, title="Agent Request", color="green")

        while True:
            result = self.ask(prompt, use_tools=True, memory=True)

            if not result.calls:
                result = results.parse_response(result.content, result.metrics)

                # We need to make sure we have steps, and they are not empty
                if result.data and "steps" in result.data and result.data["steps"]:

                    # We want to make sure the manager is only selecting sub-agent steps
                    required_annotation = None if run_type == "plan" else {"fractale.type": "agent"}
                    errors = StepsValidator(result.data["steps"]).validate(required_annotation)
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
            found = False
            agent_call = step.get("tool") or step.get("agent")
            if "prompt" in step and step["prompt"] in self.prompt_map:
                step["schema"] = self.prompt_map.get(step["prompt"])
                new_steps.append(step)
                found = True
            # This is a fractale agent, we set as a tool call
            elif "agent" in step and agent_call in self.tool_map:
                step["schema"] = self.tool_map.get(agent_call)
                step["type"] = "tool"
                new_steps.append(step)
                found = True
            elif "tool" in step and step.tool in self.tool_map:
                step["schema"] = self.tool_map.get(step["tool"])
                # Force the type to be tool, we don't have a use case for it to not be
                step["type"] = "tool"
                new_steps.append(step)
                found = True
            if not found:
                raise ValueError(f"Call {step.name} is not a known tool, prompt, or agent.")
        return new_steps
