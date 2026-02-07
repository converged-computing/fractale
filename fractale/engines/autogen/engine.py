import asyncio
import logging
import re
import sys

import autogen

import fractale.engines.autogen.agents as helpers
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


# Errors and prompts, etc.
termination_protocol = """### TERMINATION PROTOCOL
When you have completed the task and produced the final output:
1. Output the succinct result as instructed.
2. End your message with the exact phrase: WORKFLOW COMPLETE"""

init_msg = "Begin task.\n\nCONTEXT:\n%s"


def check_termination(msg):
    """
    Function to determine if we are done. Jank.
    """
    content = msg.get("content", "")
    return content and re.search("(COMPLETE|TERMINATE|FINISH)", content) is not None


def format_context(d):
    return "\n".join([f"{k}: {v}" for k, v in d.items() if not k.startswith("_")])


class Manager(AgentBase):
    """
    Executes a Fractale Plan using Microsoft AutoGen agents.
    """

    def __init__(self, plan, backend=None, ui=None, max_attempts=None, database=None):
        self.plan = plan
        self.backend = backend
        self.ui = ui or CLIAdapter()
        self.max_attempts = max_attempts or 10
        self.database = database
        self.client = None
        self.reset()

    def run(self, context):
        """
        Run the agent.
        """
        context = get_context(context)

        # Update with global inputs
        for k, v in self.plan.global_inputs.items():
            if k not in context:
                context[k] = v

        self.init()

        # Check that we have all tools/prompts we need
        asyncio.run(self.connect_and_validate())

        # TODO we are missing the actual state machine transform her
        # what to do on success vs. failure
        # need a lookup of stuff.
        # We also need a way to determine when something is successful or fail.

        try:
            self.metadata["status"] = "running"
            tracker = asyncio.run(self.run_loop(context))
            self.metadata["status"] = "Succeeded"
            self.save_results(tracker)
            self.ui.on_workflow_complete("Success")
            return tracker

        except Exception as e:
            self.metadata["status"] = "Failed"
            logger.error(f"AutoGen Engine Failed: {e}")
            self.ui.on_workflow_complete("Failed")
            raise e

    async def connect_and_validate(self):
        """
        Connect and validate the client with the plan for both prompts and tools.
        """
        async with self.client:
            server_prompts = await self.client.list_prompts()
            p_list = (
                server_prompts.prompts if hasattr(server_prompts, "prompts") else server_prompts
            )
            prompt_schema_map = {p.name: {a.name for a in (p.arguments or [])} for p in p_list}

            # 2. Fetch and map Tool schemas
            server_tools = await self.client.list_tools()
            t_list = server_tools.tools if hasattr(server_tools, "tools") else server_tools

            # MCP tools use JSON Schema in inputSchema.
            # We extract the top-level property names for validation.
            tool_schema_map = {}
            for t in t_list:
                schema = t.inputSchema if hasattr(t, "inputSchema") else {}
                properties = schema.get("properties", {}).keys() if isinstance(schema, dict) else []
                tool_schema_map[t.name] = set(properties)

            # 3. Validate and set schemas on plan steps
            for step in self.plan.states.values():
                if step.type == "agent":
                    if step.prompt in prompt_schema_map:
                        step.set_schema(prompt_schema_map[step.prompt])
                    else:
                        sys.exit(f"⚠️  Prompt '{step.prompt}' not found on server during init.")

                elif step.type == "tool":
                    # Determine tool name from step (usually step.name or a tool attribute)
                    tool_name = getattr(step, "tool", step.name)
                    if tool_name in tool_schema_map:
                        step.set_schema(tool_schema_map[tool_name])
                    else:
                        sys.exit(f"⚠️  Tool '{tool_name}' not found on server during init.")

    async def get_helper_agents(self, cfg):
        """
        Initialize helper agents for a run. We assume any agents that
        preserve memory are done in the context of one loop run.
        """
        return {"schema": helpers.SchemaHelper(cfg)}

    def exceeded_attempts(self, attempts, step):
        """
        Have we exceeded max attempts?
        """
        if step.name not in attempts:
            attempts[step.name] = 0
        attempts[step.name] += 1
        if attempts[step.name] > self.max_attempts:
            logger.info(f"Reached max attempts for {step.name}")
            return True
        return False

    def fail(self, step, steps):
        """
        Given a particular step, fail it.
        Update state machine steps. Return a boolean to determine if we should
        globally fail the workflow.
        """
        return self.change_state("failed", step, steps)

    def succeed(self, step, steps):
        """
        Given a particular step, pass it.
        Return boolean to determine if we should globally end (succeed) workflow.
        """
        return self.change_state("success", step, steps)

    def change_state(self, state, step, steps):
        """
        Shared function to change state (failed, success).
        """
        transition = step.transitions.get(state)
        if not transition:
            self.ui.log(f"No '{state} option, ending workflow.")
            return True
        self.ui.log(f"Transition => {transition}")
        steps.insert(0, self.plan.states[transition])

    async def run_loop(self, context):
        """
        Main async running loop
        """
        tracker = []
        timer = Timer()

        # Model config for agents (shared for now)
        cfg = get_agent_config(context)

        # Create and get lookup of helper agents
        agents = await self.get_helper_agents(cfg)

        # Let's use max attempts globally
        attempts = {}
        async with self.client:

            # Start in the intiial state. We don't know where we will go from there.
            state = self.plan.initial_state
            steps = [self.plan.states[state]]

            while steps:
                step = steps.pop(0)
                result = error = None

                # Update max attempts, exit if we hit it
                if self.exceeded_attempts(attempts, step):
                    break

                # Prepare a prompt and get the inputs for a tool or prompt call
                print(f"Generating Arguments for Step Call {step.name}")
                inputs = await agents["schema"].get_validated_arguments(step, context)
                self.ui.on_step_start(step.name, step.description, inputs)

                # For each call type we provide:
                # 1. The step object (with full inputs, variables, etc.)
                # 2. The model config to create agents
                # 3. Inputs specific to the step
                with timer:
                    try:
                        if step.type == "agent":
                            result = await self.run_agent(step, cfg, inputs)
                        elif step.type == "tool":
                            result = await self.run_tool(step, cfg, inputs)
                    except Exception as e:
                        error = str(e)

                # We are requiring json all around.
                self.ui.log(f"Transition options: {step.transitions}")

                # Clean Markdown before JSON parsing
                if result and not error:

                    # This assumes there is a parseable result
                    # We get around issue of maybe not by telling agent can generate empty one
                    result = await agents["schema"].require_json(result)

                    # We don't have a result, this is considered failure
                    if not result:
                        if self.fail(step, steps):
                            break
                        continue

                    # Otherwise, we succeeded
                    self.ui.on_step_finish(step.name, str(result), error, {})
                    print("THIS IS THE RESULT")
                    print(result)
                    print("THIS IS THE CONTEXT")
                    print(context)

                    # Store raw previous result
                    # TODO need a cleaner way to move between stuff here.
                    context["previous_result"] = result
                    context[f"{step.name}_result"] = result
                    context.update(result)
                    context.result = result

                    if self.succeed(step, steps):
                        break

                tracker.append(
                    {
                        "step": step.name,
                        "duration": timer.elapsed_time,
                        "result": result,
                        "error": error,
                    }
                )

                if error:
                    raise RuntimeError(f"Step {step.name} failed: {error}")

        return tracker

    async def run_agent(self, step, cfg, args):
        """
        Async function to run agent.

        An agent call has to have a prompt, because that determines what the agent is instructed
        to do. If we do not have a prompt we are just explicitly calling a tool.
        """
        logger.info(f"📥 Fetching Persona: {step.prompt}")

        try:
            response = await self.client.get_prompt(step.prompt, arguments=args)
            instruction = "\n\n".join(
                [
                    m.content.text if hasattr(m.content, "text") else str(m.content)
                    for m in response.messages
                ]
            )

        # This probably shouldn't happen, let's see.
        except Exception as e:
            raise RuntimeError(f"Error rendering prompt '{step.prompt}': {e}")

        # Inject extra instruction from plan, and termination protocol
        instruction += step.spec.get("instruction") or ""
        instruction += termination_protocol

        # AssistantAgent and ProxyAgent by default do not carry memory
        max_attempts = step.spec.get("max_attempts", self.max_attempts)
        assistant = autogen.AssistantAgent(
            name="worker",
            system_message=instruction,
            llm_config=cfg,
        )
        user_proxy = autogen.UserProxyAgent(
            name="user_proxy",
            human_input_mode="NEVER",
            code_execution_config=False,
            is_termination_msg=check_termination,
            max_consecutive_auto_reply=max_attempts,
        )

        # If we allow tools, the agent can see (and use and call) them
        if getattr(step, "allow_tools", True):
            await register_mcp_capabilities(assistant, user_proxy, self.client)

        # I am testing being more open here to give the agent MORE context
        result = await user_proxy.a_initiate_chat(
            assistant, message=init_msg % format_context(step.spec)
        )
        return self.extract_chat_result(result)

    def extract_chat_result(self, chat_res):
        """
        If the agent has conversation we lose the result.
        We need to walk backwards and retrieve it. This is really annoying.
        """
        history = chat_res.chat_history
        if not history:
            return ""

        print("THIS IS THE HISTORY")
        print(history)
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

    async def run_tool(self, step, cfg, args):
        """
        Run a direct tool.
        """
        tool_name = step.tool
        logger.info(f"🛠️ AutoGen Manager executing tool: {tool_name}")
        result = await self.client.call_tool(tool_name, args)
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
