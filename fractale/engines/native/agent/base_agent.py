import asyncio
import json
import time

import fractale.engines.native.backends as backends
import fractale.engines.native.result as results
from fractale.core.config import ModelConfig
from fractale.engines.base import AgentBase
from fractale.logger.logger import logger


class AgentBase(AgentBase):
    """
    State machine agent base
    """

    agent_result_truncate = 800

    def run(self, context):
        """
        Main entry point called by the Manager.

        run -> run_loop (prompt) -> process_loop (inner loop)
        """
        start_time = time.time()
        self.metadata["status"] = "running"

        # Setup fastmcp client and choose a backend (before async)
        self.init()
        self.init_backend(context)

        try:
            result = asyncio.run(self.run_loop(context))
            self.metadata["status"] = "success"

        except Exception as e:
            self.metadata["status"] = "failed"
            result = results.StepResult(str(e))

        finally:
            self.metadata["times"]["execution"] = time.time() - start_time

        result.show(truncate=self.agent_result_truncate)
        return result

    async def call_tool(self, call, metrics=None):
        """
        Call a tool, requested from an agent.
        Return a parsed result.
        """
        result = None
        if call["args"]:
            args = json.dumps(call["args"])
            logger.panel(args, title=f"🛠️  Calling: {call['name']}", color="cyan", truncate=800)
        else:
            logger.info(f"🛠️  Calling: {call['name']}")
            result = await self.client.call_tool(call["name"], call["args"])
            result = results.parse_response(result, metrics)
            result.show()
        return result

    def init_backend(self, context=None):
        """
        Create the backend from the model config.
        """
        cfg = ModelConfig.from_context(context)
        if cfg.provider not in backends.BACKENDS:
            raise ValueError(f"Provider '{cfg.provider}' not supported.")
        self.backend = backends.BACKENDS[cfg.provider](config=cfg)
