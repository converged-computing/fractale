from rich import print

from fractale.ui.base import UserInterface


class CLIAdapter(UserInterface):
    """
    Basic command line client
    """

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

    def on_workflow_complete(self, status):
        print(f"\n🏁 Workflow: '{status}'")

    def ask_user(self, question, options=None):
        """
        Standard Python input
        """
        opt_str = f"[{'/'.join(options)}]" if options else ""
        return input(f"❓ {question} {opt_str}: ").strip()
