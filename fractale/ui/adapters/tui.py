import json
import logging
import queue
import traceback

from rich.panel import Panel
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import (
    Collapsible,
    Footer,
    Header,
    Label,
    LoadingIndicator,
    Log,
    Markdown,
    Static,
)

from fractale.ui.base import UserInterface
from fractale.ui.screens import UserInputScreen

logger = logging.getLogger("fractale")


class TextualAdapter(UserInterface):
    """
    Translate abstract UI calls (from manager) into thread-based actions.
    """

    def __init__(self, app: "FractaleApp"):
        self.app = app

    def on_step_update(self, content: str):
        """
        Called by Agent to show live tool output in the UI.
        """
        # Update the output box.
        self.app.call_from_thread(self.app.action_set_result, str(content))

    def on_step_start(self, name: str, description: str, inputs: dict):
        prompt_text = inputs.get("_debug_prompt_text", "")
        self.app.call_from_thread(self.app.action_add_step, name, description)

    def on_log(self, message: str, level: str = "info"):
        self.app.call_from_thread(self.app.action_log, message)

    def on_step_finish(self, name: str, result: str, error: str, metadata: dict):
        if error:
            self.app.call_from_thread(self.app.action_log, f"[bold red]ERROR:[/bold red] {error}")
            self.app.call_from_thread(self.app.action_status, "Step Failed", "red")
        else:
            self.app.call_from_thread(self.app.action_set_result, str(result))
            self.app.call_from_thread(self.app.action_status, "Step Complete", "green")

    def on_prompt_loaded(self, text: str):
        self.app.call_from_thread(self.app.action_update_prompt, text)

    def on_workflow_complete(self, status: str):
        self.app.call_from_thread(self.app.action_status, f"Done: {status}", "blue")

    def ask_user(self, question: str, options: list[str] = None) -> str:
        """
        Blocking call.
        1. Creates a Queue.
        2. Signals App to show Modal.
        3. Waits for Modal to put result in Queue.
        """
        reply_queue = queue.Queue()
        self.app.call_from_thread(self.app.action_prompt_user, question, reply_queue)
        return reply_queue.get()


class StepDisplay(Collapsible):
    """
    A widget representing one Step.
    Contains nested collapsibles for Reasoning and Output.
    """

    def __init__(self, title: str, description: str, **kwargs):
        super().__init__(title=title, **kwargs)
        self.description = description

        # Logs
        self.log_widget = Log(highlight=True, classes="step-log")

        # Results
        self.result_container = Vertical(classes="step-result-container")
        self.container_result = Collapsible(title="📝 Output")

        # Write "thinking" here.
        self.container_log = Collapsible(title="🧠 Reasoning & Tools")
        self.container_result = Collapsible(title="📝 Output")

        # Write prompt neatly here.
        self.prompt_widget = Markdown("", classes="step-prompt")
        self.container_prompt = Collapsible(title="📋 System Instruction / Prompt")

    def compose(self) -> ComposeResult:
        yield Label(f"Goal: {self.description}", classes="step-desc")

        # Mount Prompt Section
        with self.container_prompt:
            yield self.prompt_widget

        with self.container_log:
            yield self.log_widget

        with self.container_result:
            yield self.result_container

        yield LoadingIndicator()

    def on_mount(self):
        # Hide all initially
        self.container_prompt.display = False
        self.container_log.display = False
        self.container_result.display = False

    def write_log(self, message: str):
        """Reveal log section and write message."""
        if not self.container_log.display:
            self.container_log.display = True
            self.container_log.collapsed = False  # Auto-expand on first log

        if not isinstance(message, str):
            message = json.dumps(message)
        self.log_widget.write_line(message)

    def start_loading(self):
        """
        Mounts a LoadingIndicator if one isn't already present.
        """
        # Query to see if we already have one (prevent duplicates)
        if not self.query(LoadingIndicator):
            indicator = LoadingIndicator()
            # Insert it right after the description label
            self.mount(indicator, after=self.query_one(".step-desc"))

    def stop_loading(self):
        """
        Removes the LoadingIndicator from the DOM.
        """
        # Query all indicators in this widget and remove them
        for widget in self.query(LoadingIndicator):
            widget.remove()

    def set_prompt(self, text: str):
        if not text:
            return
        self.container_prompt.display = True
        self.prompt_widget.update(text)
        self.container_prompt.collapsed = True

    def set_result(self, content: str):
        """
        Robust result rendering. Always shows SOMETHING.
        """
        self.stop_loading()

        # 1. Reveal Container
        self.container_result.display = True
        self.container_result.collapsed = False
        self.result_container.remove_children()

        # 2. Handle Empty Content explicitly
        if not content:
            self.result_container.mount(Label("[dim]No output returned[/dim]"))
            return

        try:
            # 3. Attempt Structured Rendering
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                # Fallback: Wrap raw string in a dict so the loop handles it
                data = {"Raw Output": str(content)}

            # Normalize non-dict JSON (e.g. lists or primitives)
            if not isinstance(data, dict):
                data = {"Result": data}

            for key, value in data.items():
                title = str(key).replace("_", " ").title()

                # Default renderable
                renderable = str(value)

                # Pretty print complex types
                if isinstance(value, (dict, list)):
                    renderable = Pretty(value)

                # Syntax highlight multiline strings
                elif isinstance(value, str) and "\n" in value:
                    renderable = Syntax(value, "text", theme="monokai", word_wrap=True)

                # Mount the panel
                # Use height="auto" to ensure it expands to content
                panel = Panel(renderable, title=title, border_style="green", expand=True)
                self.result_container.mount(Static(panel, classes="result-panel"))

        except Exception as e:
            # 4. Nuclear Fallback: If Rich rendering crashes, show raw error + content
            error_msg = f"Rendering Error: {e}\n\nRaw Content:\n{content}"
            self.result_container.mount(Label(error_msg))


class FractaleApp(App):
    CSS = """
    /* Main Step Container */
    StepDisplay {
        margin-bottom: 1;
        background: $surface;
        border: solid $primary;
        height: auto;
    }

    /* The Description Label */
    .step-desc {
        text-style: italic;
        color: $text-muted;
        padding: 1;
        width: 100%;
    }

    /* Nested Collapsibles (Reasoning / Output) */
    StepDisplay > Collapsible {
        margin-top: 1;
        margin-left: 2; /* Indent slightly */
        margin-right: 2;
        background: $surface-darken-1;
        border-left: solid $accent;
    }

    /* The actual Log Widget */
    .step-log {
        height: auto;
        max-height: 20; /* Limit height so it doesn't dominate */
        background: $surface-darken-2;
        overflow-y: scroll;
        border: none;
    }

    /* The Result Markdown */
    .step-result {
        height: auto;
        padding: 1;
        background: $surface-darken-2;
    }

    .step-result-container {
        height: auto;
        background: $surface-darken-1;
        padding: 1;
    }

    StepDisplay > .Collapsible--header {
        background: $primary-darken-2;
        color: $text;
        text-style: bold;
    }

    LoadingIndicator {
        height: 1;
        min-height: 1;
        margin: 1 2;
        color: $accent;
        background: transparent;
    }

    StepDisplay {
        /* Ensure the body background is distinct */
        background: $surface;
        margin-bottom: 1;
        border: solid $primary;
    }
    .result-panel {
        height: auto;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.current_step_widget = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(id="steps-container")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Fractale Workflow"

        # Create a log so we can write errors during startup
        self.action_add_step("System", "Initialization & Validation")
        self.run_worker(self.run_process, exclusive=True, thread=True)

    def run_process(self):
        """
        The Background Worker.
        """
        adapter = TextualAdapter(app=self)
        self.manager.ui = adapter

        try:
            self.call_from_thread(self.action_stop_loading)
            self.manager.run()
        except Exception as e:
            tb = traceback.format_exc()
            self.call_from_thread(self.action_log, "\n[bold red]💥 CRITICAL FAILURE[/bold red]")
            self.call_from_thread(self.action_log, f"{e}")
            self.call_from_thread(self.action_log, f"\n[dim]{tb}[/dim]")
            self.call_from_thread(self.action_status, "Workflow Failed", "red")
        finally:
            self.call_from_thread(self.action_stop_loading)

    def action_stop_loading(self):
        if self.current_step_widget:
            self.current_step_widget.stop_loading()

    def action_update_prompt(self, text: str):
        if self.current_step_widget:
            self.current_step_widget.set_prompt(text)

    def action_add_step(self, name: str, desc: str, prompt_text: str = ""):
        container = self.query_one("#steps-container")
        if self.current_step_widget:
            self.current_step_widget.stop_loading()
            self.current_step_widget.collapsed = True

        step = StepDisplay(title=f"▶️ {name}", description=desc)
        step.collapsed = False
        container.mount(step)

        # Populate the prompt immediately if available
        if prompt_text:
            step.set_prompt(prompt_text)

        step.scroll_visible()
        self.current_step_widget = step

    def action_log(self, message: str):
        if self.current_step_widget:
            self.current_step_widget.write_log(message)
        else:
            self.notify(message, severity="error", timeout=10)

    def action_set_result(self, content: str):
        if self.current_step_widget:
            self.current_step_widget.title = self.current_step_widget.title.replace("▶️", "✅")
            self.current_step_widget.set_result(content)
            self.current_step_widget.collapsed = True

    def action_status(self, msg: str, style: str):
        # If status indicates failure, stop spinner
        if "Failed" in msg and self.current_step_widget:
            self.current_step_widget.title = self.current_step_widget.title.replace("▶️", "❌")

        self.sub_title = msg

    def action_prompt_user(self, question: str, reply_queue):
        def on_input_done(result: str):
            reply_queue.put(result)

        self.push_screen(UserInputScreen(question), on_input_done)
