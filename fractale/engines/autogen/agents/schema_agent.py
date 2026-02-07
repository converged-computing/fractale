import json
import logging

from autogen import AssistantAgent
from rich import print

import fractale.utils as utils
from fractale.tools.calls import get_tool_prompt

logger = logging.getLogger(__name__)

# Error templates

fix_error_prompt = (
    "Your previous response resulted in an error:\n%s\n\n"
    "Please fix the error and provide the corrected JSON arguments."
)
validation_error = "Validation Error: The following arguments are NOT allowed in the schema: %s. Please only use these keys: %s."
jsonmap_error = "The JSON returned is not an object/dictionary. Please return a JSON map."
json_decode_error = "JSON Decode Error: %s. Please check your commas and quotes."


class SchemaHelper:
    """
    A utility specialist that uses a single, interleaved user-message
    to extract validated JSON arguments.
    """

    def __init__(self, cfg, max_attempts=None):
        """
        We primarily need the llm model config (cfg) to create the helper
        """
        self.max_attempts = max_attempts or 10

        # AssistantAgent and ProxyAgent by default do not carry memory
        # We don't need a model_client because we pass the llm_config
        self.agent = AssistantAgent(
            name="schema_specialist",
            # I am not adding a system message because I don't want different
            # parts of the prompt biased.
            system_message="",
            llm_config=cfg,
        )

    def check_json(self, text):
        """
        Require text to be json parseable.
        """
        error = None
        args = {}
        data = utils.extract_code_block(text)

        # Do we already have json dict?
        if isinstance(text, dict):
            return text, error

        # Case 1: Invalid json load?
        try:
            args = json.loads(data)
            if not isinstance(args, dict):
                error = jsonmap_error
        except json.JSONDecodeError as e:
            error = json_decode_error % str(e)
        return args, error

    async def get_validated_arguments(self, step, context):
        """
        This is the main purpose of this schema helper agent.
        Executes a loop with the agent to get valid JSON arguments.
        Retries automatically if JSON is malformed or violates the schema.
        """
        attempts = 0

        # Before we start a step, we generate a prompt to ask for the right inputs
        # the right inputs will depend on the last outcome and what the function needs
        step_context = context.copy().data
        step_context.update(step.spec.get("inputs") or {})

        # TODO this assumes that the options (the functions) do not change
        # We need to redo the call to the server if they do
        current_prompt = get_tool_prompt(step.name, step.type, list(step.schema), step_context)
        print(current_prompt)

        while attempts < self.max_attempts:
            attempts += 1
            logger.info(f"Attempt {attempts} to get validated arguments for {step.name}")
            message = {"content": current_prompt, "role": "user"}

            # pass the history to allow the agent to see previous errors
            # We are knowingly not using TextMessage and autogen_agentchat
            response = self.agent.generate_reply([message])

            # Require json response!
            args, error = self.check_json(response["content"])

            # Something outside of schema?
            if not error:
                # This is checking if there are keys in the args not in the schema
                extra = set(args.keys()) - step.schema
                if extra:
                    error = validation_error % (list(extra), list(step.schema))

            # No error, return arguments for call (tool or prompt)
            if not error:
                logger.info(f"✅ Successfully validated arguments for {step.name}")
                return args

            # If we are here, something went wrong. Ask the agent to fix it.
            logger.warning(f"⚠️ Attempt {attempts} failed: {error}")

            # Feed the error back as the next user prompt
            current_prompt = fix_error_prompt % error

        # There is probably some larger issue to be addressed.
        raise RuntimeError(
            f"Failed to get valid arguments for '{step.name}' after {self.max_attempts} attempts."
        )

    async def require_json(self, response, agent=None, max_attempts=None):
        """
        Helper parser agent that will retry if the json result does not parse.
        """
        attempts = 0
        max_attempts = max_attempts or self.max_attempts
        agent = agent or self.agent
        while attempts < self.max_attempts:
            attempts += 1
            logger.info(f"Attempt {attempts} to get valid json for {agent}")

            # Allow for passing content response directly
            if isinstance(response, dict) and "content" in response:
                response = response["content"]

            # Require json response!
            args, error = self.check_json(response)

            # No error, return arguments for call (tool or prompt)
            if not error:
                logger.info(f"✅ Successfully parsed json for {agent}")
                return args

            # If we are here, something went wrong. Ask the agent to fix it.
            logger.warning(f"⚠️ Attempt {attempts} failed: {error}")

            # Feed the error back as the next user prompt
            # pass the history to allow the agent to see previous errors
            message = {"content": fix_error_prompt % error, "role": "user"}
            response = self.agent.generate_reply([message])

        logger.warning(f"Maximum attempts {attempts} reached for {agent}, giving up.")
