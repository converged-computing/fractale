import asyncio
import json
import time

from rich import print

import fractale.engines.native.backends as backends
import fractale.engines.native.result as results
import fractale.utils as utils
from fractale.logger.logger import logger
from fractale.tools.calls import check_call_results

from .base_agent import AgentBase
from .helper_agent import DebugAgent


class WorkerAgent(AgentBase):
    """
    A standalone worker for the Native Engine.
    Executes a single step using FastMCP + LLM Backend.
    No inheritance from global base classes.
    """

    def __init__(self, name: str, step=None, ui=None, max_attempts=None):
        self.name = name

        # The agent is responsible for a step.
        # this is basically a config for the workflow step
        self.step = step
        self.ui = ui
        self.max_attempts = max_attempts or 5
        self.client = None
        self.metadata = {
            "name": name,
            "status": "pending",
            "times": {},
            "steps": [],
        }
        # Debug Agent
        self.debug_agent = DebugAgent()

    def run(self, context):
        """
        Main entry point called by the Manager.

        run -> run_loop (prompt) -> process_loop (inner loop)
        """
        start_time = time.time()
        self.metadata["status"] = "running"

        # Setup fastmcp client and choose a backend (before async)
        self.init()
        self.init_backend(context)

        try:
            result = asyncio.run(self.run_loop(self.step.prompt, context))
            self.metadata["status"] = "success"

        except Exception as e:
            self.metadata["status"] = "failed"
            result = results.StepResult(str(e))

        finally:
            self.metadata["times"]["execution"] = time.time() - start_time

        result.show()
        return result

    async def run_loop(self, prompt, context):
        """
        Sets up connections and runs the async loop.
        """
        async with self.client:

            # Derive the persona (prompt) from mcp server.
            inputs = utils.resolve_templates(
                inputs=self.step.spec.get("inputs", {}), context=context, schema=self.step.arguments
            )
            instruction = await self.fetch_persona(prompt, inputs)

            # Since we are moving between steps, add the context
            instruction += self.add_context(instruction, context, self.step.arguments)

            # Once we get here, we have a specific instruction (with a persona)
            # And we want to allow the agent to work on the task in a loop
            response = await self.process_loop(instruction, context)

        return response

    def add_context(self, instruction, context, arguments=None):
        """
        Appends the Blackboard variables to the system prompt so the LLM knows the state of the world.
        """
        arguments = arguments or {}
        if not context:
            return instruction

        info = "\n\n### SHARED CONTEXT\n"
        info += "The following variables are available from previous steps:\n\n"

        for k, v in context.items():
            if k in arguments:
                continue
            if isinstance(v, (dict, list)):
                val_str = json.dumps(v, indent=2)
            else:
                val_str = str(v)
            info += f"- **{k}**: {val_str}\n"
        return instruction + info

    async def fetch_persona(self, prompt, arguments):
        """
        Calls MCP Server to render the prompt string.

        This sets the personality of the agent.
        """
        self.ui.log(f"📥 Persona: {prompt}")

        try:
            result = await self.client.get_prompt(name=prompt, arguments=arguments)
            msgs = []
            for msg in result.messages:
                # Assume a prompt server returns a single prompt message
                msgs.append(json.loads(msg.content.text)["messages"][0]["content"]["text"].strip())

            return "".join(msgs) + (self.step.spec.get("instruction") or "")
        except Exception as e:
            raise RuntimeError(f"Failed to fetch persona '{prompt}': {e}")

    def show_instruction(self, instruction):
        """
        Show instruction up to 500 characters
        """
        instruction = self.get_instruction(instruction)
        if len(instruction) > 800:
            instruction = instruction[:800] + " ... "
        logger.panel(instruction, title="Agent Instruction")

    def get_instruction(self, instruction):
        # Assume prmopt message, but fall back to text
        try:
            return json.loads(instruction)["messages"][0]["content"]["text"].strip()
        except:
            return instruction

    async def process_loop(self, instruction, context):
        """
        We need to return on some state of success or ultimate failure.
        """
        max_loops = context.get("max_attempts") or self.max_attempts
        loops = 0
        result = None

        # Are we allowed to use tools?
        has_tools = self.step.tool or self.step.tools
        use_tools = self.step.allow_tools or has_tools

        # Each step internally can go up to some max tries
        while loops < max_loops:
            # Start counting at 1. Like Matlab
            loops += 1
            self.show_instruction(instruction)

            # This is making an agentic call, with or without tools
            response, metrics, calls = self.backend.generate_response(
                prompt=instruction,
                use_tools=use_tools,
                tools=self.step.tools,
                # Use memory so we remember the initial prompt
                memory=True,
            )

            # Quick return if no tool callss
            if not calls:
                result = results.parse_response(utils.get_code_block(response), metrics)

                # But if we have calls, better determine the state
                transition = self.step.match_rules(result.data or result.content)
                if transition:
                    result.transition = transition
                if result is not None:
                    result.attempts = loops
                return result

            # Process all calls requested by LLM
            tool_results = []
            for call in calls:
                self.ui.log(f"🛠️  Calling: {call['name']} with args {call['args']}")
                result = await self.client.call_tool(call["name"], call["args"])
                result = results.parse_response(result, metrics)
                call["result"] = result.content

                # Give the agent the tool result and ask to continue or return
                tool_results.append(call)

            if tool_results:
                instruction = check_call_results(tool_results)

            # No error? We assume this is criteria for finishing the step
            elif not result.error:
                print(f"{self.step.prefix} There was no error.")
                break

            # If there is an error, we update the instruction to show it, or run out of loops and exit
            print(f"{self.step.prefix} There WAS an error.")

            # Use the debug agent to generate a response to give back
            response = self.debug_agent.ask(result.error)
            logger.panel(response.content, title="Debug Agent Response", color="blue")
            instruction = response.content

        if result is not None:
            result.attempts = loops
        return result
