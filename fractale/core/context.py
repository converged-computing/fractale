import collections

from fractale.logger import logger


def get_context(context):
    """
    Get or create the context.
    """
    if isinstance(context, Context):
        return context
    return Context(context)


class Context(collections.UserDict):
    """
    A custom dictionary that allows attribute-style access to keys,
    and extends the 'get' method with a 'required' argument.

    The context for an agent should be populated with metadata that
    needs to move between agents. The manager decides what from the
    context to pass to agents for an updated context.
    """

    def __init__(self, *args, **kwargs):
        # args[0] is typically the dict object
        # Filter out those that come from the client (noise)
        args = (self.filter_cli_args(args[0]),)
        super().__init__(*args, **kwargs)

    def filter_cli_args(self, args):
        """
        Filter known arguments from the client
        """
        updated = {}
        skips = ["debug", "quiet", "config_dir", "version", "command", "plan", "mode", "engine"]
        for k, v in args.items():
            if k in skips:
                continue
            updated[k] = v
        return updated

    def reset(self):
        """
        Reset the return code and result.
        """
        for key in ["return_code", "result", "error"]:
            self.data[key] = None

    def __getattribute__(self, name):
        """
        Intercepts all attribute lookups (including methods/functions)
        """
        try:
            # Step 1: this would be a normal attribute
            attr = object.__getattribute__(self, name)
        except AttributeError:
            # Then handle lookup of dict key by attribute
            return super().__getattribute__(name)

        # Step 2: We allow "get" to be called with defaults / required.
        if name == "get":
            original_get = attr

            def custom_get(key, default=None, required=False):
                """
                Wrapper for the standard dict.get() method.
                Accepts the custom 'required' argument.
                """
                if required:
                    if key not in self.data:
                        raise ValueError(f"Key `{key}` is required but missing")
                        logger.exit(f"Key `{key}` is required but missing", title="Context Status")

                    # If required and found, just return the value
                    return self.data[key]
                else:
                    # If not required, use the original dict.get behavior
                    return original_get(key, default)

            # Return the wrapper function instead of the original method
            return custom_get

        # 4. For any other attribute (like keys(), items(), update(), or custom methods)
        # return the attribute we found earlier
        return attr

    # 5. Override __getattr__ to handle attribute-style access to dictionary keys
    def __getattr__(self, name):
        """
        Allows access to dictionary keys as attributes.
        """
        if name in self.data:
            return self.data[name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        """
        Allows setting keys via attribute assignment.
        """
        # If the attribute name is a reserved name (like 'data'), set it normally
        if name in ("data", "_data"):
            super().__setattr__(name, value)

        # Otherwise, treat it as a dictionary key
        else:
            self.data[name] = value
