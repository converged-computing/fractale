import inspect
import re
from typing import List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt


def is_callable(executable):
    """
    Determine if an executable (class) is callable.
    """
    return hasattr(executable, "__call__") and inspect.iscoroutinefunction(executable.__call__)


def get_user_validation(
    message: str,
    options: Optional[List[str]] = None,
    default: str = "y",
    choices: Optional[List[str]] = None,
    is_markdown: bool = False,
) -> str:
    """
    Asks the user for validation.
    Accepts:
      - 'y' / 'yes' -> returns "yes"
      - 'n' / 'no' -> returns "no"
      - 'f' / 'feedback' -> prompts for a string and returns the feedback text.
    """
    choices = choices or ["y", "n", "f", "yes", "no", "feedback"]
    console = Console()

    # If options were passed (like the regex proposal), show them in the panel
    display_message = message
    if options:
        options_list = "\n".join([f"• {opt}" for opt in options])
        display_message = f"{message}\n\n[bold white]Context/Options:[/bold white]\n{options_list}"

    if is_markdown:
        display_message = Markdown(display_message)

    console.print(
        Panel(
            display_message,
            title="[bold violet]Validation Required[/bold violet]",
            expand=False,
        )
    )

    # Prompt for the specific semantic choices
    # We use y/n/f as short keys for speed
    choice = Prompt.ask(
        "[bold yellow]Confirm ([green]y[/green]es/[red]n[/red]o) or provide ([cyan]f[/cyan])eedback[/bold yellow]",
        choices=choices,
        default=default,
    ).lower()

    # Handle "Yes"
    if choice in ["y", "yes"]:
        return "yes"

    # Handle "No"
    if choice in ["n", "no"]:
        return "no"

    # Handle "Feedback"
    if choice in ["f", "feedback"]:
        feedback_answer = Prompt.ask("[bold cyan]Enter your feedback/correction[/bold cyan]")

        # Validation: Feedback cannot be empty
        # Recursively call to ensure we get a result
        if not feedback_answer or feedback_answer.strip() == "":
            console.print("[italic red]Feedback cannot be empty.[/italic red]")
            return get_user_validation(message, options, default)
        return feedback_answer.strip()

    # Fallback recursive safety
    return get_user_validation(message, options, default)


def get_user_input(
    message: str,
    options: Optional[List[str]] = None,
    default: Optional[str] = None,
    allow_extra: Optional[bool] = True,
    extra_options: Optional[list] = None,
) -> str:
    """
    Asks the user for input. If options are provided, uses numbered selection.
    Recursively asks again if the user provides an empty response without a default.
    """
    console = Console()

    def try_again(answer, message, options, default):
        """
        Determine if we need to try again (or just return answer)
        """
        if answer is None or (isinstance(answer, str) and answer.strip() == ""):
            console.print("[italic red]Input cannot be empty. Please try again.[/italic red]")
            return get_user_input(message, options, default)
        return answer

    if options:

        # Always allow the user to ask for something else
        if allow_extra:
            options += extra_options or ["Something else"]

        # 1. Create mapping: "1" -> "Option Text"
        numbered_map = {str(i): opt for i, opt in enumerate(options, 1)}

        # 2. Build display string
        numbered_choices_str = "\n".join(
            f"[bold cyan]{num}[/bold cyan]. {text}" for num, text in numbered_map.items()
        )

        console.print(
            Panel(
                f"{message}\n\n{numbered_choices_str}",
                title="[bold violet]Input Requested[/bold violet]",
                expand=False,
            )
        )

        # 3. If the default is the text of an option, find its number
        default_num = None
        if default:
            for num, text in numbered_map.items():
                if text == default:
                    default_num = num
                    break

        # 4. Prompt for number
        choice_key = Prompt.ask(
            "[bold yellow]Select a number[/bold yellow]",
            choices=list(numbered_map.keys()),
            default=default_num,
        )

        # Recursive check (though rich.Prompt usually forces a choice if 'choices' is set)
        if not choice_key:
            return get_user_input(message, options, default)

        choice = numbered_map[choice_key]

        # If we have the "something else" response:
        if choice == len(numbered_map) - 1:
            answer = Prompt.ask(f"[bold violet]{message}[/bold violet]", default=default)
            return try_again(answer, message, options, default)
        return numbered_map[choice_key]

    else:
        answer = Prompt.ask(f"[bold violet]{message}[/bold violet]", default=default)

        # If user pressed Enter and there was no default
        return try_again(answer, message, options, default)


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
