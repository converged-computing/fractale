import logging
import os
from typing import Dict, List

import yaml

import fractale.utils as utils

logger = logging.getLogger(__name__)


class LocalToolRegistry:
    """
    Global singleton to store local tools.

    This is fairly simple - it's just a way to store a global set of
    tools that we add from a plan (that need to be get-table by later
    instances or creations of agents).
    """

    _tools: List[Dict[str, str]] = []

    @classmethod
    def load_registries(cls, registry_paths: List[str]):
        """
        Reads one or more YAML files and appends their tools to the global registry.
        Expects YAML format:
        tools:
          - path: module.path.Tool
        """
        for path in registry_paths or []:
            if not os.path.exists(path):
                raise ValueError(f"Registry file not found: {path}")

            new_tools = utils.read_yaml(path).get("tools", [])
            if isinstance(new_tools, list):
                cls._tools.extend(new_tools)
                logger.info(f"Loaded {len(new_tools)} tool(s) from {path}")

    @classmethod
    def configure(cls, tools_config: List[Dict[str, str]]):
        """
        Set or overwrite the tool configuration directly.
        """
        cls._tools = tools_config

    @classmethod
    def get_tools(cls) -> List[Dict[str, str]]:
        """
        Retrieve all tool blueprints gathered during this process run.
        """
        return cls._tools


def set_local_tools(config: List[Dict[str, str]]):
    LocalToolRegistry.configure(config)
