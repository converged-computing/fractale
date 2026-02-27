import json

from rich.box import ROUNDED
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fractale.engines import get_engine


def display_mcp_tools(tools):
    console = Console()

    for tool in tools:
        # 1. Detect if it's an Agent or a Tool via annotations
        annotations = tool.inputSchema.get("annotations", {})
        is_agent = annotations.get("fractale.type") == "agent"

        # UI Styling
        header_color = "bold magenta" if is_agent else "bold green"
        type_tag = "🤖 AGENT" if is_agent else "🛠️  TOOL"

        # 2. Build the Title
        title = Text.assemble(
            (f" {type_tag} ", "reverse " + header_color), (f" {tool.name} ", "bold white on black")
        )

        # 3. Build Input Arguments Table
        input_table = Table(
            show_header=True,
            header_style="bold cyan",
            box=ROUNDED,
            expand=True,
            title="[dim]Input Schema[/dim]",
        )
        input_table.add_column("Arg", style="bold yellow", width=15)
        input_table.add_column("Type", style="green", width=10)
        input_table.add_column("Description", style="white")

        props = tool.inputSchema.get("properties", {})
        required = tool.inputSchema.get("required", [])

        for prop_name, details in props.items():
            req_mark = "[red]*[/red]" if prop_name in required else " "
            input_table.add_row(
                f"{prop_name}{req_mark}",
                str(details.get("type", "any")),
                details.get("description", "n/a"),
            )

        # 4. Build Output Table (if outputSchema exists)
        renderables = [Text(f"\n{tool.description}\n", style="italic gray70"), input_table]

        if tool.outputSchema and tool.outputSchema.get("properties"):
            output_table = Table(
                show_header=True,
                header_style="bold blue",
                box=ROUNDED,
                expand=True,
                title="[dim]Output Schema[/dim]",
            )
            output_table.add_column("Returns", style="bold blue", width=15)
            output_table.add_column("Type", style="green", width=10)
            output_table.add_column("Description", style="white")

            out_props = tool.outputSchema.get("properties", {})
            for prop_name, details in out_props.items():
                output_table.add_row(
                    prop_name, str(details.get("type", "any")), details.get("description", "n/a")
                )
            renderables.append(output_table)

        # 5. Print the Panel using a Group to combine renderables
        console.print(
            Panel(
                Group(*renderables),
                title=title,
                title_align="left",
                border_style=header_color,
                padding=(0, 2),
                expand=False,
            )
        )


def main(args, extra, **kwargs):
    """
    Run an agent workflow using the configured engine.
    """
    # Instantiate the Engine (native state machine)
    engine = get_engine(
        engine=args.engine,
        backend=args.backend,
        max_attempts=args.max_attempts,
    )
    tools = engine.get_local_tools()
    if args.json:
        tools = [x.model_dump() for x in tools]
        print(json.dumps(tools, indent=4))
    else:
        display_mcp_tools(tools)
