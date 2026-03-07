import asyncio
import copy
import json

import fractale.core.result as results
import fractale.utils as utils
from fractale.core.plan.validate import StepsValidator
from fractale.engines.native.agent.helper_agent import HelperAgent
from fractale.logger.logger import logger

boolia = f"""If you are CERTAIN about the output structure of a sub-agent from an output schema you MAY define "rules" that determine success or failure of the sub-agent. The "rules" is a dictionary, and within the dictionary the keys MUST correspond to "failure" and/or "success." Each entry in the dictionary MUST be a list of strings to be evaluated against the code result returned by the tool or agent to trigger the condition. We use the library on pypi boolia. Here are examples.

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

You MAY ask questions to the user to formulate the sub-agent prompt. You SHOULD first use tool calls to clarify before writing this prompt. Assume the sub-agent should run without uncertainy.
The sub-agent will orchestrate a scoped task, and have access to the same tool endpoints that you see. You should return a single step under a list, where the step has the structure {{"name": "<name>", "agent": "<agent_tool_endpoint_name>", "type": "agent"}}. Arguments are key value pairs under "inputs."
{boolia}

If you are missing information or a tool, you MUST ask the user for clarification. You MUST tell the sub-agent to retry if a step is erroneous.
Here is the user goal: %s

You MUST come up with a sub-agent prompt. To prompt the user for more information or ask a question, respond with a json structure with "prompt" and we will return the answer. You can add "options" to the "prompt" if you want to limit the user to a set of choices, and "default" to set a default choice. You MUST inspect the environment (resources, data) and have confidence about what you are going to run before you return the final single step list. It MUST be a single step list of steps under a "steps" key in the format requested.
"""


class ManagerAgent(HelperAgent):
    """
    Interact with the user to derive a plan.
    """

    # Metadata for discovery by the Planner/Manager
    name = "planner"
    description = (
        "A sub-agent planner that interactively works with the user to explore the "
        "environment and derive a single, scoped sub-agent step to execute a task."
    )

    input_schema = {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "The high-level goal or task the user wants to accomplish.",
            },
            "max_turns": {
                "type": "integer",
                "default": 100,
                "description": "The maximum number of reasoning/discovery turns allowed.",
            },
        },
        "annotations": {"fractale.type": "agent"},
        "required": ["instruction"],
    }

    output_schema = {
        "type": "object",
        "properties": {
            "success": {
                "type": "boolean",
                "description": "Whether a valid plan step was generated.",
            },
            "steps": {
                "type": "array",
                "items": {"type": "object"},
                "description": "A list containing the single generated state machine step.",
            },
            "summary": {
                "type": "string",
                "description": "A summary of the reasoning used to create the step.",
            },
            "error": {
                "type": "string",
                "description": "Error details if the planning phase failed.",
            },
        },
        "required": ["success"],
    }
    # TODO vsoch: allow this to be a sub-agent (e.g., add the annotation?)

    agent_result_truncate = 1000

    async def __call__(self, step, **kwargs):
        return await self.run_loop(step, **kwargs)

    async def run_loop(self, step, **kwargs):
        """
        Perform the debug task and return a Helper agent response
        """
        await self.set_lookup_maps()

        # Extract run_type for validation logic
        run_type = kwargs.get("run_type", "plan")

        prompt = manager_step_prompt % step.instruction

        # Hide the larger instruction from the user
        logger.panel(step.instruction, title="Agent Request", color="green")

        while True:
            result = self.ask(prompt, use_tools=True, memory=True)

            if not result.calls:
                result = results.parse_response(result.content)

                # We need to make sure we have steps, and they are not empty
                if result.data and "steps" in result.data and result.data["steps"]:

                    # Set schemas for steps
                    result.data["steps"] = self.set_step_maps(result.data["steps"])

                    # We want to make sure the manager is only selecting sub-agent steps
                    required_annotation = None if run_type == "plan" else {"fractale.type": "agent"}
                    errors = StepsValidator(result.data["steps"]).validate(required_annotation)
                    if errors:
                        prompt = f"Your plan needs work:\n{errors}"
                        continue

                    # Check with user that steps are ok (only yes or feedback)
                    preview = self.get_steps_preview(result.data["steps"])
                    is_ok = await self.ask_validate_user(
                        f"Is this plan OK?\n```json\n{preview}\n```\n",
                        choices=["yes", "y", "feedback", "f"],
                    )

                    # First we need to validate the steps
                    if is_ok == "yes":
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
                    # Note: You likely wanted to keep the manager_step_prompt context here
                    prompt = manager_step_prompt % step.instruction + " " + prompt

                # prompt the user with whatever the LLM is presenting
                else:
                    prompt = await self.ask_user(result.content)
                    logger.panel(prompt, title="User Answer")
                    prompt = manager_step_prompt % step.instruction + " " + prompt

            else:
                tool_calls = []
                async with self.mcp_client:
                    for call in result.calls:
                        result_tool = await self.call_tool(call)
                        if result_tool is not None:
                            tool_calls.append(result_tool.content)

                prompt = "Here are the results from your calls:" + "\n".join(tool_calls)

    def get_steps_preview(self, steps):
        """
        Show the user a preview. We leave out inputs/outputs for brevity.
        """
        updated = []
        for step in steps:
            step = copy.deepcopy(step)
            del step["schema"]
            updated.append(step)

        return json.dumps(updated, indent=4)

    async def ask_user(self, prompt, options=None, default=None):
        """
        Ask the user to respond to a question without blocking the event loop.

        We first try to show structured output. For models that aren't as good, they do
        not follow instructions, and we just prompt the user for a response to return.
        """
        try:
            return await asyncio.to_thread(utils.get_user_input, prompt, options, default)
        except:
            return await asyncio.to_thread(utils.ask_user_prompt(prompt))

    async def ask_validate_user(
        self, message, options=None, default=None, choices=None, is_markdown=True
    ):
        """
        Ask the user to respond to a question without blocking the event loop.
        """
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
        Set maps for steps. All prompts/tools should be known.
        """
        new_steps = []
        for step in steps:
            found = False
            agent_call = step.get("tool") or step.get("agent")
            if "prompt" in step and step["prompt"] in self.prompt_map:
                step["schema"] = self.prompt_map.get(step["prompt"])
                new_steps.append(step)
                found = True
            elif "agent" in step and agent_call in self.tool_map:
                step["schema"] = self.tool_map.get(agent_call)
                step["type"] = "tool"
                new_steps.append(step)
                found = True
            elif "tool" in step and step.get("tool") in self.tool_map:
                step["schema"] = self.tool_map.get(step["tool"])
                step["type"] = "tool"
                new_steps.append(step)
                found = True
            if not found:
                # Get the name safely for the error message
                name = step.get("name", "unnamed step")
                raise ValueError(f"Call {name} is not a known tool, prompt, or agent.")
        return new_steps
