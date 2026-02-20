import importlib
import inspect
import os
from typing import Dict, List

from mcp.types import Tool
from rich import print

import fractale.utils as utils
from fractale.logger.logger import logger

tools = None


class LocalToolRegistry:
    """
    Global singleton to store local tools.

    This is fairly simple - it's just a way to store a global set of
    tools that we add from a plan (that need to be get-table by later
    instances or creations of agents).
    """

    def __init__(self, paths):
        # Maps tool names to callables (functions or class instances)
        # and keep the tool definitions from discovery
        self.registry = {}
        self.definitions = []
        self.load(paths)

    def load(self, registry_paths: List[str]):
        """
        Reads one or more YAML files and appends their tools to the global registry.
        Expects YAML format:
        tools:
          - path: module.path.Tool
        """
        tools = []
        for path in registry_paths or []:
            if not os.path.exists(path):
                raise ValueError(f"Registry file not found: {path}")

            new_tools = utils.read_yaml(path).get("tools", [])
            if isinstance(new_tools, list):
                tools.extend(new_tools)

        # Bind newly loaded tools
        logger.info(f"Loaded {len(tools)} tool(s) from {path}")
        self.bind(new_tools)

    def bind(self, tools: List[Dict[str, str]]):
        """
        Import and instantiate local tools.
        A path can point to a class or a function. If a class, we instantiate
        pointing to "self" equivalent, and then expect a __call__.
        """
        for tool in tools:

            # We require a path.
            if "path" not in tool:
                print(f"Warning: tool definition {tool} is missing a 'path' attribute.")
                continue
            path = tool["path"]

            # E.g., fractale.agents.parsers.ResultParserAgent
            try:
                mod_path, obj_name = path.rsplit(".", 1)
                module = importlib.import_module(mod_path)
                obj = getattr(module, obj_name)
            except Exception as e:
                logger.error(f"Failed to load local tool '{path}': {e}")
                continue

            # Case 1: sub-agent class with __call__ and metadata attributes
            if inspect.isclass(obj):
                new_tool = self.load_class_tool(obj, obj_name)
                logger.debug(f"Bound local sub-agent: {new_tool.name}")

            # Case 2: standard function
            else:
                new_tool = self.load_function_tool(obj, obj_name)
                logger.debug(f"Bound local tool: {new_tool.name}")

            self.definitions.append(new_tool)

    def has(self, name):
        return name in self.registry

    def get(self, name):
        return self.registry.get(name)

    def load_class_tool(self, cls, cls_name):
        """
        Load a class tool, providing the AgentBase here as self for the backend
        """
        instance = cls()
        name = getattr(instance, "name", cls_name.lower())
        self.registry[name] = instance
        return Tool(
            name=name,
            description=getattr(instance, "description", cls.__doc__ or ""),
            inputSchema=getattr(instance, "input_schema", {"type": "object"}),
        )

    def get_tools(self):
        return self.definitions

    def load_function_tool(self, func):
        """
        Load a function tool, more standard/typical.
        """
        name = getattr(func, "name", func.__name__)
        self.registry[name] = func
        return Tool(
            name=name,
            description=func.__doc__ or "Local utility function",
            inputSchema=getattr(func, "input_schema", {"type": "object"}),
        )


def init_registry(paths):
    global tools

    # Global tools registry
    tools = LocalToolRegistry(paths)
    return tools
