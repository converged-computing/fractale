import importlib
import inspect
import json
import os
import sys
from typing import Callable, Dict, List

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.types import Tool

import fractale.core.registry as registry
import fractale.core.result as results
import fractale.utils as utils
from fractale.core.config import ModelConfig
from fractale.logger.logger import logger


class AgentBase:

    def __init__(self):
        # Maps tool names to callables (functions or class instances)
        # and keep the tool definitions from discovery
        self._local_registry: Dict[str, Callable] = {}
        self._local_tool_definitions: List[Tool] = []

        # This will be set in self.init()
        self.mcp_client = None
        self.reset()

    def reset(self):
        """
        Reset the agent state.
        """
        self._chat_all_tools = None
        self._chat_no_tools = None
        self._chat_with_tools = None

    def init(self):
        """
        Setup the mcp client for the state machine. We use
        the streaming http transport from fastmcp. We also add
        local tools (sub-agents or functions)
        """
        port = os.environ.get("FRACTALE_MCP_PORT", "8089")
        token = os.environ.get("FRACTALE_MCP_TOKEN")
        url = f"http://127.0.0.1:{port}/mcp"
        headers = {"Authorization": token} if token else None
        transport = StreamableHttpTransport(url=url, headers=headers)
        self.mcp_client = Client(transport)

        # These are local tools, which can be classes (with __call__) or functions
        # This allows us to add one-off sub-agents to the orchestrator
        self._bind_local_tools(registry.LocalToolRegistry.get_tools())

    def ask(self, prompt, memory=False):
        """
        Simplified handy version of generate response without additional metadata.
        This assumes no calls or tools - we just want a text response.
        """
        response, _, _ = self.generate_response(prompt, use_tools=False, memory=memory, tools=None)
        return response

    def _bind_local_tools(self, tools: List[Dict[str, str]]):
        """
        Import and instantiate local tools.
        A path can point to a class or a function. If a class, we instantiate
        pointing to "self" equivalent, and then expect a __call__.
        """
        for tool in tools:

            # We require a path.
            if "path" not in tool:
                print("Warning: tool definition {tool} is missing a 'path' attribute.")
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

            self._local_tool_definitions.append(new_tool)

    def load_class_tool(self, cls, cls_name):
        """
        Load a class tool, providing the AgentBase here as self for the backend
        """
        instance = cls(backend=self)
        name = getattr(instance, "name", cls_name.lower())
        self._local_registry[name] = instance
        return Tool(
            name=name,
            description=getattr(instance, "description", cls.__doc__ or ""),
            inputSchema=getattr(instance, "input_schema", {"type": "object"}),
        )

    def load_function_tool(self, func):
        """
        Load a function tool, more standard/typical.
        """
        name = getattr(func, "name", func.__name__)
        self._local_registry[name] = func
        return Tool(
            name=name,
            description=func.__doc__ or "Local utility function",
            inputSchema=getattr(func, "input_schema", {"type": "object"}),
        )

    async def list_tools(self):
        """
        Combines tools from the remote MCP server and the local registry.
        """
        # A tool listing is combined real (server MCP) tools and our faux local
        tools = []
        if self.mcp_client:
            async with self.mcp_client:
                tools = await self.mcp_client.list_tools()
                tools = tools.tools if hasattr(tools, "tools") else tools  # Yo, dawg...

        # Return the merged list of Tool objects
        return list(tools) + self._local_tool_definitions

    async def connect_and_validate(self):
        """
        Connect and validate the client with the plan for both prompts and tools.
        """
        async with self.mcp_client:
            prompts = await self.mcp_client.list_prompts()
            p_list = prompts.prompts if hasattr(prompts, "prompts") else prompts
            prompt_map = {p.name: p.model_dump() for p in p_list}

            all_tools = await self.list_tools()
            tool_map = {t.name: t.inputSchema for t in all_tools}

            # Validate plan steps
            for step in self.plan.states.values():
                if step.type == "agent":
                    if step.prompt and step.prompt in prompt_map:
                        step.set_schema(prompt_map[step.prompt])
                    else:
                        logger.warning(f"⚠️ Prompt '{step.prompt}' not found on server.")

                elif step.type == "tool":
                    if step.tool in tool_map:
                        step.set_schema(tool_map[step.tool])
                    else:
                        logger.warning(f"⚠️ Tool '{step.tool}' not found in registry.")

    async def call_tool(self, call, metrics=None):
        """
        Routes the tool call to either the Local Registry or the Remote MCP Server.
        """
        result = None
        name = call["name"]
        args = json.dumps(call.get("args") or {})

        if args:
            logger.panel(args, title=f"🛠️  Calling: {name}", color="cyan", truncate=800)
        else:
            logger.info(f"🛠️  Calling: {name}")

        # Check local registry (functions or classes with __call__) or fallback to MCP server
        if name in self._local_registry:
            result = await self.call_local_tool(name, args)
        else:
            async with self.mcp_client:
                result = await self.mcp_client.call_tool(name, args)

        result = results.parse_response(result, metrics)
        result.show()
        return result

    async def call_local_tool(self, name, args):
        """
        Call a local tool from the registry
        """
        # This is either an instantiated class or function
        executable = self._local_registry[name]

        # Check if it's a coroutine or an object with an async __call__
        if inspect.iscoroutinefunction(executable) or utils.is_callable(executable):
            return await executable(**args)
        return executable(**args)

    def init_backend(self):
        """
        Create the backend from the model config.
        """
        import fractale.agents.backends as backends

        cfg = ModelConfig.from_environment()
        if cfg.provider not in backends.BACKENDS:
            raise ValueError(f"Provider '{cfg.provider}' not supported.")
        self.backend = backends.BACKENDS[cfg.provider](config=cfg)
