import asyncio
import json
import re
import textwrap
from typing import Any, Dict

from rich import print

import fractale.utils as utils
from fractale.logger.logger import logger

GLOBAL_REGEX_CACHE: Dict[str, str] = {}

parsing_prompt = f"""You are a result parsing agent and expert. Your job is to look at an output log, and derive
a regular expression that can be used to extract an exact metric of interest. For this task we are interested to
extract this metric of interest:

%s

And here is an example log:

%s

- You MUST only return one line with a regular expression.
- You MUST NOT add any additional commentary or code blocks.
"""


class ResultParserAgent:

    # Metadata for tool registration (used to trick agent that sniffs server)
    name = "result_parser"
    description = (
        "Intelligently extracts metrics from logs by generating regex and validating with a human."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "metric_name": {"type": "string", "description": "Name of the metric to find."},
            "log_text": {"type": "string", "description": "The raw log content."},
        },
        "required": ["metric_name", "log_text"],
    }

    def __init__(self, backend):
        """
        We primarily need to inherit the mcp backend for further interaction with the server.
        """
        # Note - this is an AgentBase to expose self.backend.mcp_client and self.backend.ask
        self.backend = backend
        self.backend.reset()
        self.metadata = {"tries": {}}

    def find_match(self, regex, log):
        """
        Use several strategies to find a match
        """
        try:
            return re.findall(regex, log)
        except:
            regex = self.get_code_block(regex, "re")
            try:
                return re.findall(regex, log)
            except:
                pass

    async def __call__(self, metric_name: str, log_text: str) -> Dict[str, Any]:
        """
        The __call__ function is a cool Python trick "magic" that allows us to call a class!
        """
        global GLOBAL_REGEX_CACHE

        # Check global cache first. We should only need to derive a regex once.
        if metric_name in GLOBAL_REGEX_CACHE:
            pattern = GLOBAL_REGEX_CACHE[metric_name]
            match = self.find_match(pattern, log_text)
            return {
                "success": match is not None,
                "value": " ".join(match) if match else None,
                "method": "cache",
                "regex": pattern,
            }

        # We assume we don't have a regex here, or it doesn't work.
        # Ask Gemini to make us one based on the log
        prompt = parsing_prompt % (metric_name, log_text)
        print("Sending result parser prompt to Gemini...")

        # If the prompt has previous error, this can get too long for user to see
        print(textwrap.indent(prompt[0:1000], "> ", predicate=lambda _: True))
        if metric_name not in self.metadata["tries"]:
            self.metadata["tries"][metric_name] = 0

        # If too many retries, ask for human input/help.
        retries = 0
        attempts = []
        additional = None

        # Keep trying until we at least get a match
        match = None
        while not match:
            if additional is not None:
                prompt += "\n" + additional
            regex = self.ask(prompt, memory=True)
            additional = None

            # The last appended will be the final (correct)
            attempts.append(regex)
            print("Received parsed log result...")
            logger.custom(regex, title="[green]Result Parser[/green]", border_style="green")
            match = self.find_match(regex, log_text)
            self.metadata["tries"][metric_name] += 1

            # If we have a match, check and cut out earlier
            if match:
                result = " ".join(match)
                message = (
                    f"The agent suggests regex [yellow]{regex}[/yellow] for [bold cyan]{metric_name}[/bold cyan]:\n"
                    f"Extracted => [bold green]{result}[/bold green]\n\n"
                    f"Is this correct?"
                )
                # yes / no / feedback
                is_correct = await asyncio.to_thread(
                    utils.get_user_validation,
                    message=message,
                )

                if is_correct == "yes":
                    GLOBAL_REGEX_CACHE[metric_name] = regex
                    return {
                        "success": True,
                        "metric": metric_name,
                        "value": match,
                        "regex": regex,
                    }

                elif is_correct == "no":
                    prompt += f"\nHere is a previous attempt that produced a match but was not correct: {regex}"
                else:
                    # The user provided specific feedback/correction string
                    additional = (
                        f"The user says: '{is_correct}'. Please adjust the regex accordingly."
                    )

            # Ensure it doesn't make the same mistake...
            else:
                prompt += f"\nHere is a previous unsuccessful attempt that did not match anything: {regex}"

            # Usually this indicates a problem, start fresh
            if retries >= 5:
                prompt = parsing_prompt % (metric_name, log_text)
                self.backend.reset()
                retries = 0

            # If it's not correct, we need to try again
            retries += 1
            match = None
