import json
import logging
import re

import autogen

import fractale.engines.autogen.warnings  # noqa
import fractale.utils as utils
from fractale.core.context import get_context
from fractale.engines.autogen.backend import get_agent_config
from fractale.engines.autogen.tools import register_mcp_capabilities
from fractale.engines.base import AgentBase
from fractale.ui.adapters.cli import CLIAdapter
from fractale.utils.timer import Timer

logger = logging.getLogger(__name__)

logging.getLogger("google.auth").setLevel(logging.ERROR)
logging.getLogger("autogen").setLevel(logging.ERROR)


class Manager(AgentBase):
    """
    Executes a Fractale Plan using Microsoft AutoGen agents.
    """

    def __init__(self, plan, backend=None, ui=None, max_attempts=10, database=None):
        self.plan = plan
        self.backend = backend
        self.ui = ui or CLIAdapter()
        self.max_attempts = max_attempts
        self.database = database
        self.client = None
        self.reset()

    def run(self, context):
        """
        Run the agent.
        """
        context = get_context(context)
        context.managed = True

        for k, v in self.plan.global_inputs.items():
            if k not in context:
                context[k] = v

        self.init()
        utils.run_sync(self.connect_and_validate())

        try:
            self.metadata["status"] = "running"
            tracker = utils.run_sync(self.run_loop(context))

            self.metadata["status"] = "Succeeded"
            self.save_results(tracker)

            if self.ui:
                self.ui.on_workflow_complete("Success")
            return tracker

        except Exception as e:
            self.metadata["status"] = "Failed"
            logger.error(f"AutoGen Engine Failed: {e}")
            self.ui.on_workflow_complete("Failed")
            raise e

    async def connect_and_validate(self):
        """
        Connect and validate the client with the plan.
        """
        async with self.client:
            server_prompts = await self.client.list_prompts()
            p_list = (
                server_prompts.prompts if hasattr(server_prompts, "prompts") else server_prompts
            )
            schema_map = {p.name: {a.name for a in p.arguments} for p in p_list}

            for step in self.plan.states.values():
                if step.type == "agent":
                    if step.prompt in schema_map:
                        step.set_schema(schema_map[step.prompt])
                    else:
                        logger.warning(f"⚠️ Prompt '{step.prompt}' not found on server during init.")

    def extract_code_block(self, text):
        """
        Match block of code, assuming llm returns as markdown or code block.
        """
        match = re.search(r"```(?:\w+)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
        # Extract content from ```json ... ``` blocks if present
        if match:
            return match.group(1).strip()
        # Fall back to returning stripped text
        return text.strip()

    async def run_loop(self, context):
        """
        Main async running loop
        """
        tracker = []
        timer = Timer()

        async with self.client:
            steps_list = self.plan.raw_data.get("steps", [])

            for step_conf in steps_list:
                step_name = step_conf["name"]
                step = self.plan.states[step_name]

                # Safely get inputs
                raw_inputs = step.spec.get("inputs") or {}
                self.ui.on_step_start(step.name, step.description, raw_inputs)

                result = None
                error = None

                # Resolve inputs (safely handling empty)
                resolved_inputs = utils.resolve_templates(raw_inputs, context)
                step_context = context.copy()
                step_context.update(resolved_inputs)

                with timer:
                    try:
                        if step.type == "agent":
                            result = await self.run_agent(step, step_context)
                        elif step.type == "tool":
                            result = await self.run_tool(step, step_context)
                    except Exception as e:
                        error = str(e)

                self.ui.on_step_finish(step.name, str(result), error, {})

                if result and not error:

                    # Clean Markdown before JSON parsing
                    clean_result = result
                    if isinstance(result, str):
                        clean_result = self.extract_code_block(result)

                    # Store raw previous result
                    context["_previous_result"] = result
                    context[f"{step.name}_result"] = result

                    # Attempt JSON Parse and Merge
                    try:
                        parsed_data = None
                        if isinstance(clean_result, str) and clean_result.strip().startswith("{"):
                            parsed_data = json.loads(clean_result)
                        elif isinstance(result, dict):
                            parsed_data = result

                        if isinstance(parsed_data, dict):
                            context.update(parsed_data)
                            context.result = parsed_data
                            context[f"{step.name}_result"] = parsed_data
                    except Exception:
                        context.result = result

                tracker.append(
                    {
                        "step": step.name,
                        "duration": timer.elapsed_time,
                        "result": result,
                        "error": error,
                    }
                )

                if error:
                    raise RuntimeError(f"Step {step_name} failed: {error}")

        return tracker

    async def run_agent(self, step, context):
        """
        Async function to run agent.
        """
        llm_config = get_agent_config(context)
        context_data = getattr(context, "data", context)
        prompt_args, _ = step.partition_inputs(context_data)
        logger.info(f"📥 Fetching Persona: {step.prompt}")

        try:
            prompt_res = await self.client.get_prompt(step.prompt, arguments=prompt_args)
            system_msg = "\n\n".join(
                [
                    m.content.text if hasattr(m.content, "text") else str(m.content)
                    for m in prompt_res.messages
                ]
            )
        except Exception as e:
            raise RuntimeError(f"Error rendering prompt '{step.prompt}': {e}")

        # Inject extra instruction from plan
        extra_instruction = step.spec.get("instruction")
        if extra_instruction:
            # We treat the instruction string as a template so it can use {{ variables }}
            # Wrap in dict to use existing utility
            resolved = utils.resolve_templates({"txt": extra_instruction}, context)
            system_msg += f"\n\n### ADDITIONAL INSTRUCTIONS\n{resolved['txt']}"

        # Define conditions for termination so he doesn't keep going...
        protocol_footer = (
            "\n\n### TERMINATION PROTOCOL\n"
            "When you have completed the task and produced the final output:\n"
            "1. Output the result (e.g., the JSON or Text).\n"
            "2. End your message with the exact phrase: WORKFLOW COMPLETE\n"
        )
        system_msg += protocol_footer

        # AssistantAgent and ProxyAgent by default do not carry memory
        assistant = autogen.AssistantAgent(
            name="worker",
            system_message=system_msg,
            llm_config=llm_config,
        )

        # Also define a function...
        def check_termination(msg):
            """
            Function to determine if we are done. Since we tell agent to
            print that it is WORKFLOW COMPLETE we hope this janky text business
            actually triggers.
            """
            content = msg.get("content", "")
            if not content:
                return False
            # Check for explicit completion or JSON object conclusion
            return re.search("(COMPLETE|TERMINATE|FINISH)", content) is not None

        # Safe retrieval of max_attempts
        step_inputs = step.spec.get("inputs") or {}
        max_replies = step_inputs.get("max_attempts", self.max_attempts)

        user_proxy = autogen.UserProxyAgent(
            name="user_proxy",
            human_input_mode="NEVER",
            code_execution_config=False,
            max_consecutive_auto_reply=max_replies,
            is_termination_msg=check_termination,
        )

        if getattr(step, "allow_tools", True):
            await register_mcp_capabilities(assistant, user_proxy, self.client)

        def format_context(d):
            return "\n".join([f"{k}: {v}" for k, v in d.items() if not k.startswith("_")])

        init_msg = f"Begin task.\n\nCONTEXT:\n{format_context(context_data)}"
        chat_res = await user_proxy.a_initiate_chat(assistant, message=init_msg)
        return self.extract_chat_result(chat_res)

    def extract_chat_result(self, chat_res):
        """
        If the agent has conversation we lose the result.
        We need to walk backwards and retrieve it.
        """
        history = chat_res.chat_history
        if not history:
            return ""

        for msg in reversed(history):
            content = msg.get("content", "")
            role = msg.get("role", "")
            if not content:
                continue

            # First get assistant output
            if role == "assistant":
                if "```json" in content or (content.strip().startswith("{") and "}" in content):
                    logger.info("✅ Extracted result from Assistant JSON.")
                    return content
                if "```" in content:
                    logger.info("✅ Extracted result from Assistant Code Block.")
                    return content

            # Then get tool output
            if role == "user" or role == "tool":
                if content.strip().startswith("{"):
                    logger.info("✅ Extracted result from Tool Output.")
                    return content

        return chat_res.summary

    async def run_tool(self, step, context):
        """
        Run a direct tool.
        """
        tool_name = step.tool

        # Safely get args
        raw_args = step.spec.get("args") or {}
        tool_args = utils.resolve_templates(raw_args, context)

        logger.info(f"🛠️ AutoGen Manager executing tool: {tool_name}")

        result = await self.client.call_tool(tool_name, tool_args)

        if hasattr(result, "content") and result.content:
            return result.content[0].text
        return str(result)

    def save_results(self, tracker):
        if not self.database:
            return
        data = {
            "steps": tracker,
            "plan_source": self.plan.plan_path,
            "status": self.metadata.get("status"),
            "metadata": self.metadata,
        }
        self.database.save(data)
