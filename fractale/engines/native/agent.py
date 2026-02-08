import asyncio
import json
import time

from rich import print

# Native Engine Imports
import fractale.engines.native.backends as backends
import fractale.engines.native.result as results
import fractale.utils as utils
from fractale.core.config import ModelConfig
from fractale.engines.base import AgentBase
from fractale.logger.logger import logger
from fractale.tools.calls import check_call


class WorkerAgent(AgentBase):
    """
    A standalone worker for the Native Engine.
    Executes a single step using FastMCP + LLM Backend.
    No inheritance from global base classes.
    """

    def __init__(self, name: str, step=None, ui=None, max_attempts=None):
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
        }

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
            # instruction += self.add_context(instruction, remainder)

            # Once we get here, we have a specific instruction (with a persona)
            # And we want to allow the agent to work on the task in a loop
            response = await self.process_loop(instruction, context)

        return response

    def add_context(self, instruction, context):
        """
        Appends the Blackboard variables to the system prompt so the LLM knows the state of the world.
        """
        if not context:
            return instruction

        info = "\n\n### SHARED CONTEXT\n"
        info += "The following variables are available from inputs and previous steps:\n\n"

        for k, v in context.items():
            if isinstance(v, (dict, list)):
                val_str = json.dumps(v, indent=2)
            else:
                val_str = str(v)
            info += f"- **{k}**: {val_str}\n"
        return instruction + info

    def init_backend(self, context=None):
        """
        Create the backend from the model config.
        """
        cfg = ModelConfig.from_context(context)
        if cfg.provider not in backends.BACKENDS:
            raise ValueError(f"Provider '{cfg.provider}' not supported.")
        self.backend = backends.BACKENDS[cfg.provider](config=cfg)

    async def fetch_persona(self, prompt, arguments):
        """
        Calls MCP Server to render the prompt string.

        This sets the personality of the agent.
        """
        self.ui.log(f"📥 Persona: {prompt}")

        try:
            result = await self.client.get_prompt(name=prompt, arguments=arguments)
            msgs = [
                m.content.text if hasattr(m.content, "text") else str(m.content)
                for m in result.messages
            ]

            # Get generated prompt and add custom user instruction
            return "\n\n".join(msgs) + (self.step.spec.get("instruction") or "")
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
        return json.loads(instruction)["messages"][0]["content"]["text"].strip()

    async def process_loop(self, instruction, context):
        """
        We need to return on some state of success or ultimate failure.
        """
        max_loops = context.get("max_attempts") or self.max_attempts
        loops = 0
        result = None

        # Are we allowed to use tools?
        use_tools = self.step.allow_tools

        # If tool is set, we might force the model to one tool.
        # Obviously the use_tools needs to be true here.
        if self.step.tool is not None:
            use_tools = True

        while loops < max_loops:
            # Start counting at 1. Like Matlab
            loops += 1
            self.ui.log(f"🧠 Loop {loops}/{max_loops} [tools: {use_tools}]")
            self.show_instruction(instruction)

            # This is making an agentic call, with or without tools
            response, metrics, calls = self.backend.generate_response(
                prompt=instruction,
                use_tools=use_tools,
                tools=self.step.tools,
                # Use memory so we remember the initial prompt
                memory=True,
            )

            # Quick return if no tools
            if not calls:
                output = utils.get_code_block(response)
                return results.parse_response(output, metrics)

            # Process all calls (Parallel tool use support)
            # TODO: we should set the error and result on the context, and
            # tell the memory agent that
            tool_results = []
            for call in calls:
                t_name = call["name"]
                t_args = call["args"]
                self.ui.log(f"🛠️  Calling: {t_name} with args {t_args}")

                result = await self.client.call_tool(t_name, t_args)
                result = results.parse_response(result, metrics)
                call["result"] = result.content

                # Give the agent the tool result and ask to continue or return
                tool_results.append(call)

            if tool_results:
                check = check_call(tool_results)
                instruction = (
                    '{"messages":[{"role":"user","content":{"type":"text","text": "%s"}}]}' % check
                )

            # No error?
            elif not result.error:
                print(f"{self.tep.prefix} There was no error.")
                break

            # If there is an error, we update the instruction to show it, or run out of loops and exit
            print(f"{self.step.prefix} There WAS an error.")
            # TODO: we need an analyzer debug agent to look at the possible error.
            instruction = (
                '{"messages":[{"role":"user","content":{"type":"text","text": "%s"}}]}'
                % result.error
            )

            # TODO need to work on this part - it does not work correctly yet. Instead we are not allowing tools for now

            # If this is the first time we've used the model, add the original instruction.
            # After this chat is created, the instruction should endure in memory
            # first_check = self.backend._chat_no_tools is None
            # if first_check:
            #    check += f"\nHere is the original prompt:\n{self.get_instruction(instruction)}"
            # logger.panel(check, "Agent Check Request")

            # Get the decision to parse. This will be a new chat
            # decision, _, _ = self.backend.generate_response(
            #    prompt=check,
            #    use_tools=False,
            #    memory=True
            # )
            # decision = json.loads(utils.get_code_block(decision))
            # if decision['decision'] == "retry":
            #    instruction = f"That response was invalid. Here are the issues:\n{result.error}"
            #    instruction = '{"messages":[{"role":"user","content":{"type":"text","text": instruction}}]}'
            #    break

        return result
