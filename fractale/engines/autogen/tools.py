import json
from typing import Annotated, Any, Dict

from autogen import register_function


async def register_mcp_capabilities(assistant, user_proxy, client):
    """
    1. Fetches MCP tools.
    2. Injects tool descriptions into the System Prompt.
    3. Registers a dispatcher function with AutoGen.
    """
    # Tools schema from server
    mcp_tools = await client.list_tools()

    tool_docs = []
    for t in mcp_tools:
        schema_str = json.dumps(t.inputSchema)
        tool_docs.append(f"- {t.name}: {t.description}\n  Args: {schema_str}")

    docs_text = (
        "\n\n### AVAILABLE TOOLS\nYou can call these using the `execute_tool` function:\n"
        + "\n".join(tool_docs)
    )

    # Assistant prompt
    # append the tool docs so the LLM knows what execute_tool can do
    original_sys_msg = assistant.system_message
    assistant.update_system_message(original_sys_msg + docs_text)

    # Bridge function that autogen will actually call
    async def execute_tool(
        tool_name: Annotated[str, "The name of the MCP tool to call"],
        arguments: Annotated[Dict[str, Any], "The arguments for the tool"],
    ) -> str:
        try:
            result = await client.call_tool(tool_name, arguments)
            # Unwrap FastMCP content
            if hasattr(result, "content") and result.content:
                return result.content[0].text
            return str(result)
        except Exception as e:
            return f"Error executing {tool_name}: {e}"

    # Register with autoGen
    register_function(
        execute_tool,
        caller=assistant,
        executor=user_proxy,
        name="execute_tool",
        description="Executes an external MCP tool.",
    )
