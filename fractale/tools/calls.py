import json


def get_tool_prompt(call_name: str, call_type: str, options: dict, context: dict):
    """
    Given the name of a tool or prompt endpoint, prepare a json structure of arguments
    needed as a subset of a provided context. We don't technically need to call
    this as an endpoint - we can use it as a function to generate the prompt.
    """
    context = json.dumps(context)
    options = json.dumps(options)
    text = f"""
### PERSONA
You are a {call_type} calling expert.

### CONTEXT
We need you to prepare a json structure of arguments for an MCP {call_type} call.

### GOAL
To derive a json representation of the key value pairs (dictionary) needed to call the {call_type} '{call_name}'
Here are variables available to you:

{context}

And here are variables you MUST include for the call:
{options}

### INSTRUCTIONS
1. Analyze the provided variables that must be included for the call.
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
