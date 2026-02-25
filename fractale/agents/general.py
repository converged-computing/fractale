import asyncio
import json
from typing import Any, Dict

import fractale.utils as utils
from fractale.logger.logger import logger

# System instructions for the sub-agent
PROMPT_SYSTEM_INSTRUCTIONS = """
You are a general-purpose sub-agent assistant. Your goal is to answer the user's prompt by reasoning, using tools, or asking for clarification.

### YOUR OPERATING LOOP
1. DISCOVER: Look at the tools available to you to gather information.
2. REASON: Determine if you have enough information to answer.
3. INTERACT: If you need user input, ask a question or provide choices.
4. FINALIZE: Provide a clear, concise final response.

### OUTPUT FORMAT
You must respond with a JSON object in a markdown code block.

- If you have the final answer:
  {"response": "The final answer content"}

- If you need to ask the user a question:
  {"response": None, "question": "What is the specific parameter?", "choices": ["Option A", "Option B"]}

- If you are calling tools, continue your reasoning until you reach one of the states above.
"""


class PromptAgent:
    """
    A generic autonomous sub-agent that answers questions and handles follow-ups.
    """

    # Metadata for discovery by the Planner/Manager
    name = "ask_question"
    description = (
        "A specialist that answers complex questions or gathers information. "
        "It can use cluster tools, look up documentation, and ask the user for "
        "clarification or choices when decisions are needed."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "The question or task the agent should help with.",
            },
            "task_context": {
                "type": "string",
                "description": "Relevant background information or data.",
            },
            "max_turns": {
                "type": "integer",
                "default": 100,
                "description": "The maximum number of reasoning steps allowed.",
            },
        },
        "annotations": {"fractale.type": "agent"},
        "required": ["goal"],
    }

    def __init__(self):
        """
        The backend is injected by AgentBase.load_local_tools.
        It provides list_tools(), generate_response(), and call_tool().
        """
        self.metadata = {}

    async def __call__(
        self, goal: str, task_context: str = "", max_turns: int = 10
    ) -> Dict[str, Any]:
        """
        The internal orchestrator loop.
        """
        from fractale.agents.base import backend

        logger.info(f"🧠 [PromptAgent] Starting task: {goal}")

        # Build the initial conversation state
        current_input = (
            f"{PROMPT_SYSTEM_INSTRUCTIONS}\n\n"
            f"### USER PROMPT\n{goal}\n\n"
            f"### CONTEXT\n{task_context}"
        )

        turn = 0
        while turn < max_turns:
            turn += 1

            # 1. Ask the LLM (Enable tools so it can investigate the cluster/env)
            response_text, _, tool_calls = await backend.generate_response(
                prompt=current_input,
                use_tools=True,
                memory=True,  # Maintain history for follow-up questions
            )

            # 2. Handle Tool Calls if the AI needs more data
            if tool_calls:
                tool_results = []
                for call in tool_calls:
                    result = await backend.call_tool(call)
                    tool_results.append(f"Tool '{call['name']}' result: {result.content}")

                # Feed results back as the next "user" message
                current_input = "\n".join(tool_results)
                continue

            # 3. Parse the JSON Decision/Response
            try:
                clean_json = backend.extract_code_block(response_text)
                data = json.loads(clean_json)

                # Case A: Final Response
                if data.get("response"):
                    logger.info("✅ [PromptAgent] Final response generated.")
                    return {"success": True, "response": data["response"], "turns": turn}

                # Case B: Follow-up Question or Choices
                if data.get("question"):
                    question = data["question"]
                    choices = data.get("choices")  # Optional list

                    logger.info(f"❓ [PromptAgent] Asking user: {question}")

                    # Intermittently prompt the user using our threaded UI bridge
                    user_answer = await asyncio.to_thread(
                        utils.get_user_validation, message=question, options=choices
                    )

                    # Feed the human's answer back into the LLM loop
                    current_input = f"The user responded: {user_answer}"
                    continue

            except (json.JSONDecodeError, KeyError, TypeError):
                # If the AI didn't follow the JSON format, nudge it
                current_input = (
                    "Error: Your response must be a JSON object with either a 'response' "
                    "key or a 'question' key. Please try again."
                )

        return {
            "success": False,
            "error": f"Exceeded maximum turns ({max_turns}) without a final response.",
            "last_output": response_text,
        }
