import logging

logger = logging.getLogger(__name__)


class Step:
    """
    A step wraps a state machine step, primarily
    for easier access to stuff.
    """

    def __init__(self, spec):
        self.spec = spec
        self.schema = None

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
