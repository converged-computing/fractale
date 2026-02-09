import logging

from boolia import evaluate
from rich import print

logger = logging.getLogger(__name__)


class Step:
    """
    A step wraps a state machine step, primarily
    for easier access to stuff.
    """

    def __init__(self, spec):
        self.spec = spec
        self.schema = None

    def show(self):
        """
        Show step metadata
        """
        print(f"   {self.prefix}")
        print(f"   type: '{self.type}'")
        if self.tool:
            print(f"   call: '{self.tool}'")
        else:
            print(f"   call: '{self.prompt}'")

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

    def partition_inputs(self, full_context: dict) -> tuple[dict, dict]:
        """
        Splits context into Direct Arguments vs Supplemental Context.
        """
        # Fallback if schema missing
        if self.schema is None:
            return full_context, {}

        prompt_args = {}
        background_info = {}

        # Keys to ignore
        ignored = {
            "agent_config",
            "managed",
            "max_loops",
            "max_attempts",
            "result",
            "error_message",
            "schemas",
            "validate",
        }

        for key, value in full_context.items():
            if key in self.schema:
                prompt_args[key] = value
            elif key not in ignored:
                background_info[key] = value

        # Useful for debugging
        print(prompt_args)
        return prompt_args, background_info

    @property
    def arguments(self):
        if "inputSchema" in self.schema:
            return set(self.schema["inputSchema"]["properties"].keys())
        return set([x["name"] for x in self.schema["arguments"]])

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
        return self.spec.get("tool")

    def match_rules(self, result):
        """
        Given output from an agent, check against rules.
        https://github.com/joaofreires/boolia

        Result should be a dict (first preference) or string an LLM response
        We return the first transition state that matches a rule.
        """
        for transition, rules in (self.spec.get("rules") or {}).items():
            for rule in rules:
                if evaluate(rule, context=result):
                    print(f"Matched Rule '{rule}' for transition '{transition}'")
                    return transition

    @property
    def tools(self):
        return self.spec.get("tools")

    @property
    def inputs(self):
        return self.spec.get("inputs", {})

    @property
    def transitions(self):
        return self.spec.get("transitions", {})

    @property
    def description(self):
        return self.spec.get("description", f"Action: {self.name}")

    def get(self, key, default=None):
        return self.spec.get(key, default)
