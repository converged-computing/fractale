import copy
import logging

from boolia import evaluate
from jinja2 import BaseLoader, Environment
from rich import print

logger = logging.getLogger(__name__)


class Step:
    """
    A step wraps a state machine step, primarily
    for easier access to stuff.
    """

    def __init__(self, spec):
        self.spec = spec
        self.schema = self.spec.get("schema")
        # Inputs and outputs for jinja rendering
        self.outputs = {}

    @property
    def inputs(self):
        """
        Given inputs and schema, resolve into final current step inputs.

        This currently means we set the inputs for the current step being run. If the
        step is run again, they might change. The inputs present are always the active
        or last run.
        """
        # If we don't have arguments in the schema, assume the user was incorrect to provide
        if not self.arguments:
            return {}

        # Resolve inputs with arguments (schema inputs) and user provided inputs, alon with outputs
        inputs = self.spec.get("inputs") or {}
        env = Environment(loader=BaseLoader())
        final_inputs = {}

        # Remove self from the steps we are considering - doesn't make sense.
        workflow = copy.deepcopy(self.workflow)
        del workflow[self.name]

        # Resolve provided inputs first (Jinja resolution)
        resolved_user_inputs = {}
        for k, v in inputs.items():
            if isinstance(v, str) and "{{" in v:
                # Allow for reference of {{ steps.<name>.outputs|inputs.<name> }} || {{ self.outputs.<name> }}
                try:
                    resolved_user_inputs[k] = env.from_string(v).render({"steps": workflow})
                except Exception as e:
                    logger.warning(f"Jinja render failed for key '{k}': {e}")
                    resolved_user_inputs[k] = v
            else:
                resolved_user_inputs[k] = v

        # Reconcile with Schema
        # We only care about keys the function actually accepts
        for arg in self.arguments:
            if arg in resolved_user_inputs:
                # Plan provided it, so use it
                final_inputs[arg] = resolved_user_inputs[arg]
        return final_inputs

    def set_outputs(self, outputs):
        """
        Set outputs on the step.
        """
        if not outputs:
            self.outputs = {}
        else:
            self.outputs = outputs

    def show(self):
        """
        Show step metadata
        """
        print(f"   {self.prefix}")
        print(f"   type: '{self.type}'")
        if self.tool:
            print(f"   call: '{self.tool}'")
        if self.prompt:
            print(f"   call: '{self.prompt}'")
        if self.instruction:
            print(f"   call: prompt")

    @property
    def tools(self):
        """
        Return a list of tools
        """
        if self.tool is not None:
            return [self.tool]
        elif self.tools is not None and isinstance(self.tools, list):
            return self.tools
        return None

    def set_schema(self, schema: set):
        """
        Called by Manager after connecting to Server.
        Defines which arguments the Prompt function accepts.
        """
        self.schema = schema

    @property
    def arguments(self):
        if "inputSchema" in self.schema:
            return set(self.schema["inputSchema"]["properties"].keys())
        return set([x["name"] for x in self.schema.get("arguments") or {}])

    @property
    def prefix(self):
        return f"[[blue]{self.name}[/blue]]"

    @property
    def name(self):
        return self.spec["name"]

    @property
    def type(self):
        return self.spec.get("type", "agent")

    @property
    def initial(self):
        """Is this the start state?"""
        return self.spec.get("initial", False)

    @property
    def prompt(self):
        return self.spec.get("prompt")

    @property
    def max_attempts(self):
        return self.spec.get("max_attempts")

    @property
    def instruction(self):
        return self.spec.get("instruction")

    @property
    def allow_tools(self):
        """
        If False, the Agent is forbidden from calling tools.
        It must generate text/code.
        """
        return self.spec.get("allow_tools", True)

    @property
    def validate(self):
        return self.spec.get("validate")

    @property
    def tool(self):
        return self.spec.get("tool") or self.spec.get("")

    @property
    def agent(self):
        # Sub-agent "tool"
        return self.spec.get("agent")

    @property
    def rules(self):
        """
        Get rules, being careful to not return if we find the wrong type.
        """
        rules = self.spec.get("rules") or {}
        if not isinstance(rules, dict):
            print("Warning: rules are not a dictionary.")
            return {}
        return rules

    def match_rules(self, result):
        """
        Given output from an agent, check against rules.
        https://github.com/joaofreires/boolia

        Result should be a dict (first preference) or string an LLM response
        We return the first transition state that matches a rule.
        """
        for transition, rules in (self.rules or {}).items():
            for rule in rules:
                try:
                    if evaluate(rule, context=result):
                        print(f"Matched Rule '{rule}' for transition '{transition}'")
                        return transition
                except Exception as e:
                    print(f"Warning: rule {rule} did not evaluate: {e}")

    @property
    def tools(self):
        return self.spec.get("tools")

    @property
    def transitions(self):
        return self.spec.get("transitions", {})

    @property
    def description(self):
        return self.spec.get("description", f"Action: {self.name}")

    def get(self, key, default=None):
        return self.spec.get(key, default)
