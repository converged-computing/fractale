import os
import sys

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from fractale.logger.logger import logger


class AgentBase:
    def reset(self, plan=None):
        """
        Reset the agent. Be careful if your model client is saving state here.
        """
        self.metadata = {"status": "pending", "times": {}, "steps": []}
        if plan is not None:
            self.plan = plan

    def init(self):
        """
        Setup the mcp client for the state machine. We use
        the streaming http transport from fastmcp.
        """
        port = os.environ.get("FRACTALE_MCP_PORT", "8089")
        token = os.environ.get("FRACTALE_MCP_TOKEN")
        url = f"http://127.0.0.1:{port}/mcp"

        headers = {"Authorization": token} if token else None
        transport = StreamableHttpTransport(url=url, headers=headers)
        self.client = Client(transport)

    async def connect_and_validate(self):
        """
        Connect and validate the client with the plan for both prompts and tools.
        """
        async with self.client:
            prompts = await self.client.list_prompts()
            p_list = prompts.prompts if hasattr(prompts, "prompts") else prompts
            prompt_map = {p.name: p.model_dump() for p in p_list}

            tools = await self.client.list_tools()
            t_list = tools.tools if hasattr(tools, "tools") else tools
            tool_map = {t.name: t.model_dump() for t in t_list}

            # Validate and set schemas on plan steps
            for step in self.plan.states.values():
                if step.type == "agent":
                    if step.prompt in prompt_map:
                        step.set_schema(prompt_map[step.prompt])
                    else:
                        sys.exit(f"⚠️  Prompt '{step.prompt}' not found on server during init.")

                elif step.type == "tool":
                    if step.tool in tool_map:
                        step.set_schema(tool_map[step.tool])
                    else:
                        sys.exit(f"⚠️  Tool '{step.tool}' not found on server during init.")
