import json
import re
import time

from rich import print

# Native Engine Imports
import fractale.engines.native.backends as backends
import fractale.utils as utils
from fractale.core.config import ModelConfig
from fractale.engines.base import AgentBase
from fractale.engines.native.result import parse_tool_response
from fractale.logger import logger


class WorkerAgent(AgentBase):
    """
    A standalone worker for the Native Engine.
    Executes a single step using FastMCP + LLM Backend.
    No inheritance from global base classes.
    """

    def __init__(self, name: str, step, ui=None, max_attempts=None):
        self.name = name

        # The agent is responsible for a step.
        # this is basically a config for the step
        self.step = step
        self.ui = ui
        self.max_attempts = max_attempts or 5
        self.client = None
        self.metadata = {
            "name": name,
            "status": "pending",
            "times": {},
            "steps": [],
            "llm_usage": [],
        }

    def run(self, context):
        """
        Main entry point called by the Manager.
        Synchronous wrapper around the async execution loop.
        """
        self.ui.log(f"▶️  '{self.name}' starting...")
        start_time = time.time()
        self.metadata["status"] = "running"

        # The manager adds the step.prmopt as source prompt here
        prompt_name = context.agent_config.get("source_prompt")
        if not prompt_name:
            raise ValueError(f"Worker {self.name} missing 'source_prompt' in context.")

        try:
            result = utils.run_sync(self.run_async(prompt_name, context))
            context.result = result
            self.metadata["status"] = "success"

        except Exception as e:
            self.metadata["status"] = "failed"
            context.error_message = str(e)
            self.ui.log(f"Worker '{self.name}' failed: {e}")
            raise e

        finally:
            self.metadata["times"]["execution"] = time.time() - start_time

        return context

    async def run_async(self, prompt_name: str, context):
        """
        Sets up connections and runs the async loop.
        """
        start_exec = time.time()

        # Setup fastmcp client and choose a backend
        self.init()
        self.init_backend(context)

        async with self.client:

            # Get tools available for running session.
            mcp_tools = await self.client.list_tools()
            await self.backend.initialize(mcp_tools)

            # Derive the persona (prompt) from mcp server.
            context_data = getattr(context, "data", context)
            prompt_args, remainder = self.step.partition_inputs(context_data)
            instruction = await self.fetch_persona(prompt_name, prompt_args)

            # Since we are moving between steps, add the context
            instruction += self.add_context(instruction, remainder)

            # Once we get here, we have a specific instruction (with a persona)
            # And we want to allow the agent to work on the task in a loop
            response = await self.run_loop(instruction, context)

        self.record_usage(time.time() - start_exec)
        return response

    def add_context(self, instruction, context_dict):
        """
        Appends the Blackboard variables to the system prompt so the LLM knows the state of the world.
        """
        if not context_dict:
            return instruction

        info = "\n\n### SHARED CONTEXT\n"
        info += "The following variables are available from previous steps:\n\n"

        for k, v in context_dict.items():
            # Skip system keys if any leaked through
            if k.startswith("_") and k != "_previous_result":
                continue

            # Format value nicely
            if isinstance(v, (dict, list)):
                val_str = json.dumps(v, indent=2)
            else:
                val_str = str(v)

            info += f"- **{k}**: {val_str}\n"

        return instruction + info

    def init_backend(self, context):
        """
        Create the backend from the model config.
        """
        cfg = ModelConfig.from_context(context)
        if cfg.provider not in backends.BACKENDS:
            raise ValueError(f"Provider '{cfg.provider}' not supported.")
        self.backend = backends.BACKENDS[cfg.provider](config=cfg)

    async def fetch_persona(self, prompt_name, arguments):
        """
        Calls MCP Server to render the prompt string.
        """
        log_msg = f"📥 Persona: {prompt_name}"
        if self.ui:
            self.ui.log(log_msg)
        else:
            logger.info(log_msg)

        try:
            result = await self.client.get_prompt(name=prompt_name, arguments=arguments)

            msgs = [
                m.content.text if hasattr(m.content, "text") else str(m.content)
                for m in result.messages
            ]
            text = "\n\n".join(msgs)

            # Add user custom instruction (note does not support jinja)
            text += self.step.spec.get("instruction") or ""
            return text
        except Exception as e:
            raise RuntimeError(f"Failed to fetch persona '{prompt_name}': {e}")

    async def run_loop(self, instruction, context):
        """
        Process -> Tool -> Process loop.
        We need to return on some state of success or ultimate failure.
        """
        max_loops = context.get("max_attempts") or self.max_attempts
        step = context.agent_config["step_ref"]
        loops = 0

        # Are we allowed to use tools?
        use_tools = step.allow_tools

        # If tool is set, we might force the model to one tool.
        # Obviously the use_tools needs to be true here.
        chosen_tool = context.agent_config.get("tool")
        if chosen_tool:
            use_tools = True

        while loops < max_loops:
            loops += 1
            self.ui.log(f"🧠 Loop {loops}/{max_loops}")
            print(instruction)

            response, reason, calls = self.backend.generate_response(
                prompt=instruction,
                use_tools=use_tools,
                tools=[chosen_tool] if chosen_tool else None,
            )

            self.ui.log(reason)
            if response:
                self.ui.log(response, do_handle=False) or logger.info(f"🤖 Thought: {response}")

            if not calls and chosen_tool:

                # Try to extract arguments (usually code) from the text response
                args = self.extract_code_block(response)
                if args:
                    msg = f"⚡ Auto-triggering tool: {chosen_tool}"
                    self.ui.log(msg)

                    # Prepare arguments.
                    # If extraction returned a dict, use it.
                    # If string, we might need to map it to a specific key (e.g. dockerfile)
                    # For now, assuming extract_code_block returns the arguments structure required.
                    calls = [{"name": chosen_tool, "args": args, "id": "implicit-val"}]

            # Stopping Condition
            elif not calls:
                self.ui.log("🛑 Agent finished (No tools called).")
                return response

            tool_outputs = []
            has_global_error = False

            # Process all calls (Parallel tool use support)
            for call in calls:
                t_name = call["name"]
                t_args = call["args"]
                t_id = call.get("id")
                self.ui.log(f"🛠️  Calling: {t_name}")

                try:
                    raw_result = await self.client.call_tool(t_name, t_args)
                    parsed = parse_tool_response(raw_result)
                    content = parsed.content

                    if parsed.is_error:
                        has_global_error = True
                        if "❌" not in content and "Error" not in content:
                            content = f"❌ ERROR: {content}"

                except Exception as e:
                    content = f"❌ ERROR: {e}"
                    has_global_error = True

                # Record and UI Update
                self.record_step(t_name, t_args, content)
                self.ui.log_update(content)
                tool_outputs.append({"id": t_id, "name": t_name, "content": content})

            # If we used a specific tool, checking the result is often enough
            if chosen_tool and not has_global_error:
                return tool_outputs[-1]["content"]

            # Otherwise, ask the LLM if we are we done
            try:
                # We dump the outputs into the check prompt
                # TODO: if this isn't accurate, we should have an error code.
                # and then fall back to this.
                check_args = {"content": json.dumps([t["content"] for t in tool_outputs])}
                next_instruction = await self.fetch_persona("check_finished_prompt", check_args)

                # The prompt asks the LLM to output a JSON decision
                decision, _, _ = self.backend.generate_response(prompt=next_instruction)

                # Parse decision
                decision = json.loads(self.extract_code_block(decision))
                print(decision)

                # Return last output as result
                if decision.get("action") == "success":
                    return tool_outputs[-1]["content"]

                # TODO this isn't implemented yet, but add if needed
                # Loop continues with new instructions/feedback
                if "instruction" in decision:
                    instruction = decision["instruction"]
                else:
                    instruction = f"Tool outputs received:\n{json.dumps(tool_outputs)}\nProceed."

            except Exception as e:
                # Fallback if check prompt fails or doesn't exist
                # Just feed the tool outputs back into the main loop
                instruction = f"Tool outputs: {json.dumps(tool_outputs)}"

        return response

    def extract_code_block(self, text):
        """
        Match block of code, assuming llm returns as markdown or code block.
        """
        match = re.search(r"```(?:\w+)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

    def record_step(self, tool, args, output):
        self.metadata["steps"].append(
            {
                "tool": tool,
                "args": args,
                "output_snippet": str(output)[:200],
                "timestamp": time.time(),
            }
        )

    def record_usage(self, duration):
        """
        Record token usage for the LLM.

        TODO: need to look into metrics for other backends.
        """
        if hasattr(self.backend, "token_usage"):
            self.metadata["llm_usage"].append(self.backend.token_usage)
        # TODO: vsoch what to do with duration?


# STOPPED HERE - debug this.
# Can we use flux somehow to submit / then subscribe?
# Why can't we give the llm total control (a firecracker vm or server)?
# How do we build an orchestration state machine tool into flux based on dependncies? mcp?
