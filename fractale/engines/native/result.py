import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import fractale.utils as utils
from fractale.logger.logger import logger


@dataclass
class StepResult:
    """
    Standardized client-side view of a tool execution.
    """

    content: str
    data: Optional[Dict] = None
    metrics: Optional[Dict] = None
    transition: Optional[str] = None
    attempts: Optional[int] = None

    def dict(self):
        """
        Dump to dictionary for saving.
        """
        result = {"has_error": self.has_error}
        if self.metrics:
            result["metrics"] = self.metrics
        if self.data:
            result["data"] = self.data
        elif self.content:
            result["content"] = self.content
        if self.attempts is not None:
            result["attempts"] = self.attempts
        return result

    def show(self):
        """
        Show the result!
        """
        if self.data is not None:
            result = json.dumps(self.data)
        else:
            result = self.content
        logger.panel(result, title="Agent Result", color="blue", truncate=800)

    def retry_prompt(self, extra):
        """
        Get a retry prompt with the error.
        """
        prompt = "Your last attempt was not successful"
        if self.error:
            prompt += f":\n{self.error}"
        prompt += "\nPlease try again."
        if extra:
            prompt += "\n" + extra
        return prompt

    def add_error(self, error):
        """
        Add an error to the result.
        """
        self.data = self.data or {}
        if "errors" not in self.data:
            self.data["errors"] = []
        if isinstance(self.data["errors"], list):
            self.data["errors"].append(error)
        elif isinstance(self.data["errors"], str):
            self.data["errors"] += f"\n{error}"

    @property
    def has_error(self):
        data = self.data or {}

        # 1. We set has error if we find a parseable return code (my preference)
        if self.error:
            return True

        for term in ["return_code", "retval", "returncode", "return_value"]:
            if term in data and data[term] != 0:
                return True
        return False

    @property
    def error(self):
        """
        Attempt to get errors from function calls that return them!

        1. We need to check data first, because we can have an empty error/errors return.
        2. We only look for errors in content we can't parse (likely text response.)
        """
        data = self.data or {}
        if "error" in data and data["error"]:
            return data["error"]

        elif "errors" in data:
            # Return empty response here to indicate absence of errors
            if not data["errors"]:
                return
            return "\n".join(data["errors"])

        # Fall back to content if error is there
        if not data and self.content and re.search(self.content.lower(), "(error|fail|abort)"):
            return self.content


def parse_response(raw_response: Any, metrics: dict = None):
    """
    Parses the raw return value from fastmcp.Client.call_tool into a robust ToolResult.
    """
    # FastMCP returns an object with a 'content' list of TextContent items
    # The second also handles a ToolCall result
    if hasattr(raw_response, "content") and isinstance(raw_response.content, list):
        # Join multiple content blocks if present
        content = "\n".join([c.text for c in raw_response.content if hasattr(c, "text")])
    else:
        # Fallback for raw strings or other types
        content = str(raw_response)

    # Attempt JSON Parsing (to get structured data)
    data = None
    try:
        data = utils.get_code_block(content)
    except (json.JSONDecodeError, TypeError):
        pass
    return StepResult(content=content, data=data, metrics=metrics)
