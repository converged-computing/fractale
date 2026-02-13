import asyncio
import json
import os
from datetime import datetime

import fractale.utils as utils
from fractale.core.context import get_context
from fractale.engines.native.agent import HelperAgent
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

    def __init__(self, plan, ui=None, max_attempts=10, backend="gemini", database=None):
        self.plan = plan
        self.ui = ui or CLIAdapter()
        self.max_attempts = max_attempts
        self.backend = backend
        self.attempts = 0
        self.database = database
        self.metadata = {"status": "Pending"}
        self.init()
        # Cache for persistent agents
        self.agent_cache = {}
        self.agent = HelperAgent(name="state-machine-helper", ui=self.ui)

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

        # In this context, a loop is a retry, meaning we return to initial state
        max_loops = context.get("max_attempts") or self.max_attempts or 5

        # Start Execution Loop
        tracker = []
        loops = 1

        # Log the initial loop
        self.ui.log(f"🧠 Loop {loops}/{max_loops}")

        try:
            while loops < max_loops:
                result = sm.run_cycle()
                tracker.append(result)
                logger.info(f"🌀 State Machine Update: {result['transition']}.")

                # Are we done? We need to break from True
                self.metadata["status"] = result["state"]
                if result["state"] == "complete":
                    self.ui.log_workflow_complete(result["state"])
                    break

                # Only count as loop if we have returned to initial state
                if sm.current_state_name == self.plan.initial_state:
                    self.ui.log(f"🧠 Loop {loops}/{max_loops}")
                    loops += 1

                # No next state, we have to complete
                if not sm.current_state_name:
                    self.ui.log(f"🌀 State Machine Complete")
                    break

                # TODO Ask user what to do next
                # This doesn't work in async

            # Save and return
            self.metadata["attempts"] = loops
            self.save_results(tracker)
            return tracker

        except Exception as e:
            self.metadata["status"] = "Failed"
            logger.error(f"Orchestration failed: {e}")
            raise e

    def run_agent(self, step, context):
        """
        Runs the WorkerAgent for an 'agent' type step.
        """
        # Prefer step limit, fallback to global manager limit
        max_attempts = step.spec.get("inputs", {}).get("max_attempts", self.max_attempts)

        # Does the step want to use a cached (persistent) model?
        persist = step.spec.get("persist")

        # The worker agent will work on successfully executing a step
        agent = None
        if persist:
            agent = self.agent_cache.get(step.name)
        if agent is None:
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
        start_time = datetime.now()
        tool_args = utils.resolve_templates(
            inputs=step.spec.get("inputs", {}), context=context, schema=step.arguments
        )

        async def call():
            async with self.client:
                return await self.client.call_tool(step.tool, tool_args)

        raw_result = utils.run_sync(call())
        duration = (datetime.now() - start_time).total_seconds()
        metrics = {"duration": duration, "tool": step.name}
        result = parse_response(raw_result, metrics)
        result.show()

        # Case 1: We have explicit rules to update the step transition, and match
        transition = step.match_rules(result.data or result.content)
        if transition:
            result.transition = transition
        # Case 2: Ask an agent what the outcome is
        else:
            decision = {}
            while "result" not in decision:
                decision = self.check_tool_call(step.name, result, decision)
        return result

    def check_tool_call(self, tool_name, result, decision):
        """
        Check a tool call for an error and get a transition decision.
        """
        check = check_tool_call(tool_name, result.content)
        logger.panel(check, "Tool Check Request")
        response = self.agent.ask(prompt=check, use_tools=False, memory=True)
        try:
            decision = json.loads(utils.get_code_block(response.content))
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
