import re


def get_code_block(content, code_type=None):
    """
    Parse a code block from the response

    This was a version 1 I wrote of this.
    """
    code_type = code_type or r"[\w\+\-\.]*"
    pattern = f"```(?:{code_type})?\n(.*?)```"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return match.group(1).strip()
    if content.startswith(f"```{code_type}"):
        content = content[len(f"```{code_type}") :]
    if content.startswith("```"):
        content = content[len("```") :]
    if content.endswith("```"):
        content = content[: -len("```")]
    return content.strip()


def extract_code_block(text):
    """
    Match block of code, assuming llm returns as markdown or code block.

    This is (I think) a better variant.
    """
    match = re.search(r"```(?:\w+)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
    # Extract content from ```json ... ``` blocks if present
    if match:
        return match.group(1).strip()
    # Fall back to returning stripped text
    return text.strip()
