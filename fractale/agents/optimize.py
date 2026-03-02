import asyncio
import json
from typing import Any, Dict

import fractale.utils as utils
from fractale.logger.logger import logger

# This prompt is designed for the sub-agent to perform discovery and autonomous execution.
# It does not mention specific tools, only the requirement to use what is available.
OPTIMIZE_SYSTEM_PROMPT = """
You are an autonomous Optimization sub-agent. Your goal is to iteratively achieve the target provided by the user.

### YOUR OPERATING LOOP
1. DISCOVER: Look at the tools and prompts available to you.
2. ANALYZE: Check previous results (via database or logs) to understand the current state.
3. ACT: Decide on a configuration tweak or a task. Call the appropriate tools.
4. VALIDATE: After receiving results, evaluate the Figure of Merit (FOM).
5. DECIDE: Either "retry" with a new configuration or "stop" because the goal is met or impossible.

### CONSTRAINTS
- You MAY save all intermediate data and FOMs to the database using available storage tools.
- You MUST be precise with tool arguments.
- You MUST make tool or sub-agent or prompt requests as needed. The output will be returned to you.
- When you are finished, you MUST not call tools, and you MUST return a final JSON object with:
  {"decision": "stop", "summary": "Detailed explanation of result", "final_fom": <value>}
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
        "as parameters. A high number (e.g., more than 30) max turns is suggested."
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

    output_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "summary": {"type": "string"},
            "fom": {"type": ["number", "string", "null"]},
            "turns_taken": {"type": "integer"},
            "last_reasoning": {"type": "string"},
            "message": {"type": "string"},
            "goal": {"type": "string"},
        },
        "required": ["status"],
    }

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

            # Reason Ask the LLM what to do
            # We use use_tools=True so the LLM can emit tool calls
            # memory=True preserves the history of this sub-loop
            response_text, tool_calls = backend.generate_response(
                prompt=current_prompt,
                use_tools=True,
                memory=True,
            )

            if not response_text and not tool_calls:
                current_prompt = "Your last response was empty. Please provide your next tool call or final response."
                continue

            # 3. ACT: If the agent wants to use tools, execute them
            if tool_calls:
                current_prompt = ""
                for call in tool_calls:
                    # Execute the tool via the backend's unified dispatcher
                    tool_result = await backend.call_tool(call)

                    # Update the prompt for the next turn with the tool results
                    current_prompt += f"\nTool '{call['name']}' returned: {tool_result.content}"

            # Parse decision:: Look for the JSON stop structure in the text
            else:
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

        return {
            "status": "limit_reached",
            "message": f"Reached maximum turn limit ({max_turns})",
            "goal": goal,
        }
