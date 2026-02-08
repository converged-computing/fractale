import json
import subprocess
from typing import Annotated, Any, Dict

# We are hosting tools here that deviate a lot from a standard validation request.


def get_jobspec_validation_text(script):
    """
    Get prompt text for an initial build.
    """
    return f"""
### PERSONA
You are a job validation expert.

### CONTEXT
We need to validate a job specification for correctness.

### GOAL
I need to validate if the following job specification is correct:

```
{script}
```

### REQUIREMENTS & CONSTRAINTS
You MUST return a JSON structure with fields for 'valid' (bool) and a list of string 'reasons'. You MAY optionally add a field `issues` with a list of debugging or critique of any code.

### INSTRUCTIONS
1. Analyze the provided script above.
2. Use MUST use a jobspec validation tool for the manager if one is available otherwise use your knowledge.
3. Determine validity based on the resource section ONLY
4. The 'reasons' should ONLY be specific to resources
5. If the script includes problematic code, please include in 'issues'
6. You MUST include a 'tool_call' boolean, true or false, to indicate if you used a validation tool for validation.
7. Return a json structure with 'valid' and 'tool_call' and 'reasons' (if not valid) and 'issues'
"""


def validate_jobspec_expert(script: Annotated[str, "Batch script or job specification"]):
    """
    Get a prompt to encourage validation of a job specification.
    """
    prompt_text = get_jobspec_validation_text(script)
    return {"messages": [{"role": "user", "content": {"type": "text", "text": prompt_text}}]}
