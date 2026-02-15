from typing import Optional, Protocol

from fractale.logger import logger


class UserInterface(Protocol):
    """
    The strict contract that ManagerAgent relies on.
    Any implementation (Web, TUI, CLI) must provide these methods.
    """

    def log(self, message: str, level: str = "info", do_handle: bool = True):
        """
        Main (general) log that is akin to info.
        """
        if not message:
            return True
        if hasattr(self, "on_log"):
            self.on_log(message, level)
        else:
            # We don't want any logging here
            if do_handle:
                logger.info(message)
            return False

    def log_workflow_complete(self, *args, **kwargs):
        """
        The whole plan finishes.
        """
        if hasattr(self, "on_workflow_complete"):
            self.on_workflow_complete(*args, **kwargs)

    def ask_user(self, question: str, options: list[str] = None) -> str:
        """
        The Manager pauses until the user answers (blocking)
        """
        pass
