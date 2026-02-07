PERSONA = "You are a job specification generation expert."
CONTEXT = "We need to convert between workload manager job specification formats."


def get_transform_text(script, to_manager, from_manager, fmt="batch", error=None):
    """
    Get prompt text for an initial build.
    """
    # Derive the goal for the agent. When we provide an error, it changes to a debugging agent.
    goal = """I need to convert the provided job specification from '{from_manager}' to '{to_manager}'.
The desired output format is a '{fmt}' script."""
    if error is not None:
        goal = f"""You previously attempted to convert a job specification and it did not validate. Analyze the error and fix it
{error}"""

    return f"""
### PERSONA
{PERSONA}

### CONTEXT
{CONTEXT}

### GOAL
{goal}

### REQUIREMENTS & CONSTRAINTS
You MUST not make up directives that do not exist.
You MUST preserve as many options as possible from the original.
If there is a directive that does not translate, you MUST leave it out and add a comment about the performance implications of the omission.

### INSTRUCTIONS
1. Analyze the provided script below.
2. Write a new script and return in a json structure with a "jobspec"
3. If the input script is not a workload manager batch file, you MUST return the json jobspec structure as "noop"

{script}
"""


def transform_jobspec_expert(
    script: str, from_manager: str, to_manager: str, fmt: str = "batch", error: str = None
):
    """
    Generate a prompt to transform FROM a particular workload manager TO a particular workload manager.
    A fmt should be the jobspec format, where jobspec is the refererring to the Flux canonical JSON/YAML
    representation, and batch is a typical batch script.

    Arguments
      script (str): The batch or job specification to convert.
      from_manager (str): The name of the manager to convert FROM.
      to_manager (str): The name of the job manager to convert TO.
      fmt (str): one of "batch" or "jobspec" for a Flux canonical jobspec (in json)
    """
    prompt_text = get_transform_text(script, to_manager, from_manager, fmt="batch", error=error)
    return {"messages": [{"role": "user", "content": {"type": "text", "text": prompt_text}}]}
