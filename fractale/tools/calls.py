import json


def get_tool_prompt(call_name: str, call_type: str, options: dict, context: dict):
    """
    Given the name of a tool or prompt endpoint, prepare a json structure of arguments
    needed as a subset of a provided context. We don't technically need to call
    this as an endpoint - we can use it as a function to generate the prompt.
    """
    context = json.dumps(context)
    options = json.dumps(options)
    text = f"""### PERSONA
You are a {call_type} calling expert.

### CONTEXT
We need you to prepare a json structure of arguments for an MCP {call_type} call.

### GOAL
To derive a json representation of the key value pairs (dictionary) needed to call the {call_type} '{call_name}'
Here are variables available to you:

{context}

And here is metadata about the call. The matching you MUST do is for arguments.
{options}

### INSTRUCTIONS
1. Analyze the provided arguments that must be included for the call.
2. Select that subset from the previous provided context.
3. Prepare a json structure with the subset

### REQUIREMENTS & CONSTRAINTS
You MUST minimally include all required variables.
You MUST NOT wrap anything in a code block or return markdown
"""
    return text


def get_tool_call(call_name: str, call_type: str, options: dict, context: dict):
    """
    Given the name of a tool or prompt endpoint, prepare a json structure of arguments
    needed as a subset of a provided context. We don't technically need to call
    this as an endpoint - we can use it as a function to generate the prompt.
    """
    text = get_tool_prompt(call_name, call_type, options, context)
    return {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}


def check_call(tool, output):
    return f"""You just called the tool {tool} and here is the output:
{output}

Your job is to determine what to do next. We can:

1. The step is successful and we should mark the step as complete and return.
2. The step was erroneous, and we should try again.

You MUST assess the above output and return ONLY a json structure with a "decision" to "retry" or "complete"
"""


def check_tool_call(tool, output):
    return f"""PERSONA: You are a tool debug agent.
CONTEXT: We just called a tool {tool} and need to know if there were errors.
GOAL: Look at the tool output and determine if we should succeed or fail the step.

Here is the output of the tool:

{output}

INSTRUCTIONS:
1. You MUST assess the output to determine if the tool result is "success" or "failed."
2. If the tool has failed, you MUST provide a "reason"
3. You MUST return ONLY a json structure with a "result" ("failed" or "success") and "reason"
"""


def check_call_results(tool_calls):
    return f"""Here are the results from your tool calls:

{json.dumps(tool_calls)}

You have two options:

Please fix any errors, working toward the same goal, and generate an updated response.
If you are happy with a final result, return it as instructed without any tool calls to complete the step.
"""
