from rich import print

from fractale.logger.logger import logger
from fractale.ui.base import UserInterface


class CLIAdapter(UserInterface):
    """
    Basic command line client
    """

    def on_step_start(self, name, description, inputs):
        print(f"\n🚀 Step: '{name}'")
        print(f"   {description}")

    def on_step_update(self, content: str, title: str = None):
        """
        Called when a tool produces output, but the step isn't finished yet.
        """
        if len(content) > 500:
            content = content[:500] + "..."
        try:
            logger.panel(content, title=title)
        except:
            logger.info(title)
            print(content)

    def print(self, message):
        """
        For dict and longer structures, intended to make more succinct.
        """
        if isinstance(message, str) and len(message) > 500:
            message = message[:500]
        elif isinstance(message, dict):
            updated = {}
            # Handle one level for now - should cover most cases
            for k, v in message.items():
                if isinstance(v, str) and len(v) > 500:
                    updated[k] = v[:500]
                else:
                    updated[k] = v
            message = updated
        print(message)

    def on_log(self, message, level="info"):
        print(f"   {message}")

    def on_step_finish(self, name, result, error, metadata):
        if error:
            print(f"❌ '{name}' failed: '{error}'")
        else:
            print(f"✅ '{name}' complete.")

    def on_workflow_complete(self, status):
        print(f"\n🏁 Workflow: '{status}'")

    def ask_user(self, question, options=None):
        """
        Standard Python input
        """
        opt_str = f"[{'/'.join(options)}]" if options else ""
        return input(f"❓ {question} {opt_str}: ").strip()
