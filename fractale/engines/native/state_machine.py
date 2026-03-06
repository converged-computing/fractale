import logging

from rich import print

from fractale.agents.manager import ManagerAgent
from fractale.core.plan.step import Step

logger = logging.getLogger(__name__)


class WorkflowStateMachine:
    """
    Dynamic State Machine execution engine.
    """

    def __init__(self, states, callbacks, ui=None):
        self.states = states
        self.ui = ui

        # This is manager.run_agent and manager.run_tool
        self.current_state_name = None
        self.callbacks = callbacks
        self.set_initial_state()
        self.planner = ManagerAgent()

    def set_initial_state(self):
        """
        Set the initial state based on finding "initial"
        """
        for s in self.states.values():
            if s.get("initial"):
                self.current_state_name = s.name
                break

        if not self.current_state_name:
            # Fallback to first key that isn't a terminal
            keys = [k for k, v in self.states.items() if v.type != "final"]
            self.current_state_name = keys[0] if keys else "failed"

    def run_cycle(self):
        """
        Executes ONE state and determines the next state.

        Returns: (step_metadata, is_finished)
        """
        step = self.states[self.current_state_name]

        # Are we terminal? That sounds dark...
        if step.type == "final":
            print("Current step is final, returning finished")
            return {
                "agent": self.current_state_name,
                "state": "complete",
            }

        # Execute via callback function
        step.show()

        # An agent step type means we need to plan first.
        # A plan step type (for >1 steps) also requires the planner
        if step.type == "plan":
            plan_step_name = step.name
            self.run_planner(step)
            step = self.states[self.current_state_name]

            # Delete the plan step to be conservative
            if plan_step_name in self.states:
                del self.states[plan_step_name]

        runner = self.callbacks.get(step.type)
        if not runner:
            raise ValueError(f"No runner for type '{step.type}'")

        # This returns a result object with content and error
        result = runner(step)
        if result.error:
            print(result.error)

        # If we have output, set on the step
        step.set_outputs(result.data)

        # Determine Transition
        if result.transition is not None:
            outcome = result.transition
        else:
            outcome = "success" if not result.has_error else "failure"
        next_state = step.transitions.get(outcome)

        # Determine the next state
        # Case 1: we have no next state, but failed (ask the user)
        if outcome == "failure" and not next_state:
            logger.warning(f"Outcome is {outcome} and no next state defined.")
            transition = "retry"

        # Case 2: Proceed or complete
        else:
            transition = f"{outcome} -> {next_state}" if next_state else "complete"
            outcome = "complete" if transition == "complete" else outcome

        prev_state_name = self.current_state_name
        self.current_state_name = next_state

        print()
        workflow_done = outcome == "complete"

        return {
            "agent": prev_state_name,
            "result": result.dict(),
            "transition": transition,
            "complete": workflow_done,
            "state": outcome,
        }

    def run_planner(self, plan_step):
        """
        Run the planner. An interactive process to design steps and a plan.

        For all sub-agents, we always require the planner. This can change.
        """
        # The result here is the steps (plan) and we show a shortened version
        # The step.type (agent or plan) determines if the planner is working on a step (agent)
        # or a larger plan (plan)
        result = self.planner.run(plan_step, show_result=False, run_type=plan_step.type)
        try:
            for i, step_data in enumerate(result.data["steps"]):
                step = Step(step_data)
                # Add the workflow reference to it
                step.workflow = plan_step.workflow
                # The first step is the initial step
                if i == 0:
                    self.current_state_name = step.name
                self.states[step.name] = step
        except:
            print(f"There was an unexpected error:\n{result.content}")

    def ask_next_step(self, result):
        """
        Ask the user what to do next.
        """
        print(f"Workflow Failed at '{result['agent']}'")
        action = self.ui.ask_user("Retry?", options=["retry", "quit"])
        if action == "retry":
            self.current_state_name = result["agent"]
            logger.warning(f"🔄 User requested retry. Rewinding to {result['agent']}")
        return action
