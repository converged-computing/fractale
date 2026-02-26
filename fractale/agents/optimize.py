import asyncio
import json
from typing import Any, Dict

import fractale.utils as utils
from fractale.logger.logger import logger

# This prompt is designed for the Sub-Agent to perform discovery and autonomous execution.
# It does not mention specific tools, only the requirement to use what is available.
OPTIMIZE_SYSTEM_PROMPT = """
You are an autonomous Optimization Sub-Agent. Your goal is to iteratively achieve the target provided by the user.

### YOUR OPERATING LOOP
1. DISCOVER: Look at the tools and prompts available to you.
2. ANALYZE: Check previous results (via database or logs) to understand the current state.
3. ACT: Decide on a configuration tweak or a task. Call the appropriate tools.
4. VALIDATE: After receiving results, evaluate the Figure of Merit (FOM).
5. DECIDE: Either "retry" with a new configuration or "stop" because the goal is met or impossible.

### CONSTRAINTS
- You MUST save all intermediate data and FOMs to the database using available storage tools.
- You MUST be precise with tool arguments.
- When you are finished, you MUST return a final JSON object with:
  {"decision": "stop", "summary": "Detailed explanation of result", "final_fom": <value>}
- If you decide to retry, produce a JSON object with:
  {"decision": "retry", "reasoning": "...", "next_step": "..."}
"""


class OptimizeAgent:
    """
    A generic autonomous sub-agent that uses available MCP tools to optimize a goal.
    It manages an internal reasoning-action loop without hardcoded tool names.
    """

    # Metadata for the Registry/Orchestrator to expose this as a tool
    name = "optimize"
    description = (
        "An autonomous specialist that takes a goal, discovers available tools, "
        "and iteratively executes/tweaks tasks until an optimal result is found."
        "If you have an optimization task, this agent can use the same tool endpoints,"
        "and you should investigate the environment and options and generate a single"
        "step and tool call for this agent to execute, describing the goal and task context"
        "as parameters."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "The specific performance goal or optimization target.",
            },
            "task_context": {
                "type": "string",
                "description": "Relevant starting information, previous commands, or context.",
            },
            "max_turns": {
                "type": "integer",
                "default": 30,
                "description": "The maximum number of reasoning/action cycles allowed.",
            },
        },
        "required": ["goal"],
        "annotations": {"fractale.type": "agent"},
    }

    def __init__(self):
        """
        The backend is the LLMBackend instance which provides
        list_tools(), generate_response(), and call_tool().
        """
        self.metadata = {}

    async def __call__(
        self, goal: str, task_context: str = "", max_turns: int = 30
    ) -> Dict[str, Any]:
        """
        The internal orchestrator loop.
        """
        from fractale.agents.base import backend

        logger.info(f"🚀 Sub-Agent starting optimization loop: {goal}")

        # Initial context for this sub-session
        current_prompt = (
            f"{OPTIMIZE_SYSTEM_PROMPT}\n\n### USER GOAL\n{goal}\n\n### CONTEXT\n{task_context}"
        )
        turn = 0

        while turn < max_turns:
            turn += 1
            logger.info(f"🧠 [Sub-Agent] Turn {turn}/{max_turns}")

            # 1. DISCOVERY: Get current tools from the environment
            # This ensures the agent sees Flux, Database, and Parsers
            # available_tools = await backend.list_tools()

            # 2. REASON: Ask the LLM what to do
            # We use use_tools=True so the LLM can emit tool calls
            # memory=True preserves the history of this sub-loop
            response_text, _, tool_calls = backend.generate_response(
                prompt=current_prompt,
                use_tools=True,
                memory=True,
            )

            # 3. ACT: If the agent wants to use tools, execute them
            if tool_calls:
                for call in tool_calls:
                    # Execute the tool via the backend's unified dispatcher
                    tool_result = await backend.call_tool(call)

                    # Update the prompt for the next turn with the tool results
                    current_prompt = f"Tool '{call['name']}' returned: {tool_result.content}"

                    # If the LLM is calling a tool, it's not done yet, so we continue the loop
                    continue

            # 4. PARSE DECISION: Look for the JSON stop/retry structure in the text
            try:
                # We extract code blocks from the conversational text
                clean_json = utils.extract_code_block(response_text)
                decision_data = json.loads(clean_json)

                if decision_data.get("decision") == "stop":
                    logger.info("✅ [Sub-Agent] Terminal state reached.")
                    return {
                        "status": "completed",
                        "summary": decision_data.get("summary"),
                        "fom": decision_data.get("final_fom"),
                        "turns_taken": turn,
                    }

                if decision_data.get("decision") == "retry":
                    reasoning = decision_data.get("reasoning", "Tweak requested")
                    next_step = decision_data.get("next_step", "")

                    # Human-in-the-loop: Ask for permission before starting a new iteration
                    # This uses the UI function defined in your library
                    user_msg = f"Turn {turn}: Sub-agent proposes a retry.\nReasoning: {reasoning}\nNext: {next_step}\n\nProceed?"
                    user_ok = await asyncio.to_thread(
                        utils.get_user_validation, message=user_msg, options=["yes", "no"]
                    )

                    if user_ok != "yes":
                        return {"status": "stopped_by_user", "last_reasoning": reasoning}

                    # Feed the decision back into the loop as the next "user" prompt
                    current_prompt = f"User approved retry. Proceed with: {next_step}"

            except (json.JSONDecodeError, KeyError):
                # If no valid JSON found, the agent might just be chatting or
                # forgot the format. We nudge it in the next turn.
                current_prompt = "You must continue until you decide to 'stop'. Ensure your decision is in JSON format."

        return {
            "status": "limit_reached",
            "message": f"Reached maximum turn limit ({max_turns})",
            "goal": goal,
        }
