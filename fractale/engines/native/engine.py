import asyncio
import json
import os
from datetime import datetime

import fractale.utils as utils
from fractale.core.context import get_context
from fractale.engines.native.result import parse_response
from fractale.logger import logger
from fractale.tools.calls import check_tool_call
from fractale.ui.adapters.cli import CLIAdapter

from .agent import AgentBase, WorkerAgent
from .state_machine import WorkflowStateMachine


class Manager(AgentBase):
    """
    The Native Engine Orchestrator.
    Executes the Plan using a local Finite State Machine.
    Standalone class (No inheritance from Agent).
    """

    def __init__(
        self, plan, ui=None, results_dir=None, max_attempts=10, backend="gemini", database=None
    ):
        self.plan = plan
        self.ui = ui or CLIAdapter()

        # TODO: this is not exposed
        self.results_dir = results_dir or os.getcwd()
        self.max_attempts = max_attempts
        self.backend = backend
        self.attempts = 0
        self.database = database
        self.metadata = {"status": "Pending"}
        self.init()
        # helper agent for various tasks
        self.init_helper()

    def run(self, context):
        """
        Main entry point.
        Merges inputs, validates against server, and starts FSM loop.
        """
        context = get_context(context)

        # Global inputs from plan
        for k, v in self.plan.global_inputs.items():
            if k not in context:
                context[k] = v

        # Connect and validate against server
        asyncio.run(self.connect_and_validate())

        # Setup State Machine Engine
        # The manager here creates a state machine
        # The state machine is given callbacks for running an agent or tool, defined here.
        sm = WorkflowStateMachine(
            states=self.plan.states,
            context=context,
            callbacks={"agent": self.run_agent, "tool": self.run_tool},
            ui=self.ui,
        )

        logger.info(f"✅ State Machine Initialized: {len(self.plan.states)} states.")
        self.metadata["status"] = "running"

        # Start Execution Loop
        tracker = []
        try:
            while True:
                result = sm.run_cycle()
                tracker.append(result)

                # Are we done? We need to break from True
                self.metadata["status"] = result["state"]
                if result["state"] == "complete":
                    self.ui.log_workflow_complete(result["state"])
                    break

                # Ask user what to do next
                if result["state"] == "ask":
                    action = sm.ask_next_step(result)

                    # Implied action retry is a continue
                    if action == "quit":
                        break

            # Save and return
            self.save_results(tracker)
            return tracker

        except Exception as e:
            self.metadata["status"] = "Failed"
            logger.error(f"Orchestration failed: {e}")
            raise e

    def init_helper(self):
        self.agent = WorkerAgent(name="state-machine-helper", ui=self.ui)
        self.agent.init()
        self.agent.init_backend()

    def run_agent(self, step, context):
        """
        Runs the WorkerAgent for an 'agent' type step.
        """
        # Prefer step limit, fallback to global manager limit
        max_attempts = step.spec.get("inputs", {}).get("max_attempts", self.max_attempts)

        # The worker agent will work on successfully executing a step
        agent = WorkerAgent(
            name=step.name,
            step=step,
            max_attempts=max_attempts,
            ui=self.ui,
        )
        return agent.run(context)

    def run_tool(self, step, context=None):
        """
        Runs a deterministic Tool directly (no LLM).
        """
        logger.info(step.name)
        tool_name = step.tool
        start_time = datetime.now()
        tool_args = utils.resolve_templates(
            inputs=step.spec.get("inputs", {}), context=context, schema=step.arguments
        )
        logger.info(f"🛠️  Executing Tool: {tool_name}")

        async def call():
            async with self.client:
                return await self.client.call_tool(tool_name, tool_args)

        raw_result = utils.run_sync(call())
        duration = (datetime.now() - start_time).total_seconds()
        metrics = {"duration": duration, "tool": tool_name}
        result = parse_response(raw_result, metrics)
        result.show()

        # Ask an agent what the outcome is
        decision = {}
        while "result" not in decision:
            decision = self.check_tool_call(tool_name, result, decision)
        return result

    def check_tool_call(self, tool_name, result, decision):
        """
        Check a tool call for an error and get a transition decision.
        """
        check = check_tool_call(tool_name, result.content)
        logger.panel(check, "Tool Check Request")
        decision, _, _ = self.agent.backend.generate_response(
            prompt=check, use_tools=False, memory=True
        )
        try:
            decision = json.loads(utils.get_code_block(decision))
        except:
            return {}

        # The reason is an added error, if the LLM determines there is one
        if "reason" in decision and decision["reason"]:
            result.add_error(decision["reason"])

        # The result dictates the transition
        if "result" in decision and decision["result"] in ["success", "failure"]:
            result.transition = decision["result"]

        return decision

    def save_results(self, tracker):
        """
        Delegates saving to the configured Database backend.
        """
        if not self.database:
            return
        data = {
            "steps": tracker,
            "plan_source": self.plan.plan_path,
            "status": self.metadata.get("status"),
            "metadata": self.metadata,
        }
        self.database.save(data)
