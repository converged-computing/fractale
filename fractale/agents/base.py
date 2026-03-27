import inspect
import json
import os
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

import fractale.core.result as results
import fractale.utils as utils
from fractale.core.config import ModelConfig
from fractale.db import get_database
from fractale.logger.logger import logger

backend = None


class AgentBase:
    def __init__(self):
        self.tool_map = {}
        self.prompt_map = {}
        self.reset()
        self.init()
        # Cache tools to call once. This assumes we won't change
        self._tools = None
        self.database = get_database()

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
        self.transport = StreamableHttpTransport(url=url, headers=headers)
        self.mcp_client = Client(self.transport)

    def ask(self, prompt, memory=False):
        """
        Simplified handy version of generate response without additional metadata.
        This assumes no calls or tools - we just want a text response.
        """
        response, _ = self.generate_response(prompt, use_tools=False, memory=memory, tools=None)
        return response

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

        # Return the merged list of Tool objects, save to cache
        self._tools = list(tools) + self.get_local_tools()
        return self._tools

    @property
    def registry(self):
        """
        Convenience function to get live, local tool registry
        """
        from fractale.core.registry import tools

        return tools

    def get_local_tools(self):
        """
        Call on demand to get loaded registry tools.
        The registry tools should be loaded once on init.
        """
        return self.registry.get_tools()

    async def set_lookup_maps(self):
        """
        Set lookup maps, which include real MCP and locally registered tools.

        We separate this from validation so the manager agent can load the definitions
        without needing to validate against a plan.
        """
        async with self.mcp_client:
            prompts = await self.mcp_client.list_prompts()
            p_list = prompts.prompts if hasattr(prompts, "prompts") else prompts
            self.prompt_map = {p.name: p.model_dump() for p in p_list}

            all_tools = await self.list_tools()
            self.tool_map = {t.name: t.model_dump() for t in all_tools}

    async def connect_and_validate(self):
        """
        Connect and validate the client with the plan for both prompts and tools.
        """
        if not self.tool_map or not self.prompt_map:
            await self.set_lookup_maps()

        # Validate plan steps
        for step in self.plan.states.values():

            # A prompt coincides with a prompt endpoint
            if step.type == "prompt":
                if step.prompt and step.prompt in self.prompt_map:
                    step.set_schema(self.prompt_map[step.prompt])
                else:
                    logger.warning(f"⚠️ Prompt '{step.prompt}' not found on server.")

            # Tools are tools, agents are exposed (and used) like tools
            elif step.type in ["tool", "agent"]:
                endpoint = step.tool or step.agent
                if endpoint in self.tool_map:
                    step.set_schema(self.tool_map[endpoint])
                else:
                    logger.warning(f"⚠️ Tool or agent '{endpoint}' not found in registry.")

    async def call_tool(self, call):
        """
        Routes the tool call to either the Local Registry or the Remote MCP Server.
        """
        from fractale.agents.base import backend

        result = None
        name = call["name"]

        if call["args"]:
            args = json.dumps(call.get("args", {}))
            logger.code_panel(args, title=f"🛠️  Calling: {name}", color="cyan", language="json")
        else:
            logger.info(f"🛠️  Calling: {name}")

        # Check local registry (functions or classes with __call__) or fallback to MCP server
        self.database.start_step(name, "tool", {"inputs": call["args"]})

        # I have seen agents call tools that do not exist...
        try:
            if self.registry.has(name):
                result = await self.call_local_tool(name, call["args"])
            else:
                async with self.mcp_client:
                    result = await self.mcp_client.call_tool(name, call["args"])
        except Exception as e:
            result = f"ERROR: {e}"

        result = results.parse_response(result)

        # Some APIs (e.g., OpenAI) require adding the tool result to history
        backend.record_tool_result(call.get("id"), result.content)
        self.database.finish_step(name, "tool", {"outputs": result.data or result.content})

        result.show()
        return result

    def record_tool_result(self, tool_call_id: str, result: Any):
        """
        Called when a tool execution finishes.

        Not required by Gemini, but required by others.
        """
        pass

    async def call_local_tool(self, name, args):
        """
        Call a local tool from the registry
        """
        # This is either an instantiated class or function
        executable = self.registry.get(name)

        # Check if it's a coroutine or an object with an async __call__
        if inspect.iscoroutinefunction(executable) or utils.is_callable(executable):
            return await executable(**args)
        return executable(**args)


def init_backend():
    """
    Yes, global variables are bad practice. But it's a lazy man's way to share a common backend instance.

    # TODO this should be extended to be more of a manager. E.g., if we want more than one backend, we would
    create them here once, and then deliver (import) as needed during execution.
    """
    global backend
    import fractale.agents.backends as backends

    cfg = ModelConfig.from_environment()
    if cfg.provider not in backends.BACKENDS:
        raise ValueError(f"Provider '{cfg.provider}' not supported.")
    backend = backends.BACKENDS[cfg.provider](config=cfg)
