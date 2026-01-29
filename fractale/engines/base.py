import os

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


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
