import inspect
import logging as _logging
import os
import platform
import sys
import threading

from fastmcp.utilities.logging import get_logger
from rich import print
from rich.panel import Panel


class LogColors:
    PURPLE = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    RED = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


class ColorizingStreamHandler(_logging.StreamHandler):
    BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)
    RESET_SEQ = "\033[0m"
    COLOR_SEQ = "\033[%dm"
    BOLD_SEQ = "\033[1m"

    colors = {
        "WARNING": YELLOW,
        "INFO": GREEN,
        "DEBUG": BLUE,
        "CRITICAL": RED,
        "ERROR": RED,
    }

    def __init__(self, nocolor=False, stream=sys.stderr, use_threads=False):
        super().__init__(stream=stream)
        self._output_lock = threading.Lock()
        self.nocolor = nocolor or not self.can_color_tty()

    def can_color_tty(self):
        if "TERM" in os.environ and os.environ["TERM"] == "dumb":
            return False
        return self.is_tty and not platform.system() == "Windows"

    @property
    def is_tty(self):
        isatty = getattr(self.stream, "isatty", None)
        return isatty and isatty()

    def emit(self, record):
        with self._output_lock:
            try:
                self.format(record)  # add the message to the record
                self.stream.write(self.decorate(record))
                self.stream.write(getattr(self, "terminator", "\n"))
                self.flush()
            except BrokenPipeError as e:
                raise e
            except (KeyboardInterrupt, SystemExit):
                # ignore any exceptions in these cases as any relevant messages have been printed before
                pass
            except Exception:
                self.handleError(record)

    def decorate(self, record):
        message = record.message
        message = [message]
        if not self.nocolor and record.levelname in self.colors:
            message.insert(0, self.COLOR_SEQ % (30 + self.colors[record.levelname]))
            message.append(self.RESET_SEQ)
        print("".join(message))
        return "".join(message)


class Logger:
    def __init__(self):
        self.logger = get_logger(__name__)
        self.log_handler = [self.text_handler]
        self.stream_handler = None
        self.printshellcmds = False
        self.quiet = False
        self.logfile = None
        self.last_msg_was_job_info = False
        self.logfile_handler = None

    def cleanup(self):
        if self.logfile_handler is not None:
            self.logger.removeHandler(self.logfile_handler)
            self.logfile_handler.close()
        self.log_handler = [self.text_handler]

    def handler(self, msg):
        for handler in self.log_handler:
            handler(msg)

    def set_stream_handler(self, stream_handler):
        if self.stream_handler is not None:
            self.logger.removeHandler(self.stream_handler)
        self.stream_handler = stream_handler
        self.logger.addHandler(stream_handler)

    def set_level(self, level):
        self.logger.setLevel(level)

    def location(self, msg):
        callerframerecord = inspect.stack()[1]
        frame = callerframerecord[0]
        info = inspect.getframeinfo(frame)
        self.debug("{}: {info.filename}, {info.function}, {info.lineno}".format(msg, info=info))

    def info(self, message):
        print(f"\n[bold cyan]{message}[/bold cyan]")

    def warning(self, msg):
        self.handler(dict(level="warning", msg=msg))

    def debug(self, msg):
        self.handler(dict(level="debug", msg=msg))

    def error(self, msg):
        self.handler(dict(level="error", msg=msg))

    def exit(self, msg, return_code=1):
        self.handler(dict(level="error", msg=msg))
        sys.exit(return_code)

    def progress(self, done=None, total=None):
        self.handler(dict(level="progress", done=done, total=total))

    def shellcmd(self, msg):
        if msg is not None:
            msg = dict(level="shellcmd", msg=msg)
            self.handler(msg)

    def success(self, message):
        """
        Wrapper to add success to output for LLM.
        """
        return success(message)

    def failure(self, message):
        """
        Wrapper to add success to output for LLM.
        """
        return error(message)

    def custom(self, message, title, border_style=None, expand=True):
        if not border_style:
            print(Panel(message, title=title, expand=expand))
        else:
            print(Panel(message, title=title, border_style=border_style, expand=expand))

    def panel(self, message, title, color="green"):
        """
        Custom message / title Panel.
        """
        color = color.lower()
        title = f"[{color}]Result Parser[/{color}]"
        return self.custom(message, title, border_style=color)

    def text_handler(self, msg):
        """The default snakemake log handler.
        Prints the output to the console.
        Args:
            msg (dict):     the log message dictionary
        """
        level = msg["level"]
        if level == "info" and not self.quiet:
            self.logger.info(msg["msg"])
        if level == "warning":
            self.logger.warning(msg["msg"])
        elif level == "error":
            self.logger.error(msg["msg"])
        elif level == "debug":
            self.logger.debug(msg["msg"])
        elif level == "progress" and not self.quiet:
            done = msg["done"]
            total = msg["total"]
            p = done / total
            percent_fmt = ("{:.2%}" if p < 0.01 else "{:.0%}").format(p)
            self.logger.info("{} of {} steps ({}) done".format(done, total, percent_fmt))
        elif level == "shellcmd":
            if self.printshellcmds:
                self.logger.warning(msg["msg"])


logger = Logger()


def setup_logger(
    quiet=False,
    printshellcmds=False,
    nocolor=False,
    stdout=False,
    debug=False,
    use_threads=False,
):
    # console output only if no custom logger was specified
    stream_handler = ColorizingStreamHandler(
        nocolor=nocolor,
        stream=sys.stdout if stdout else sys.stderr,
        use_threads=use_threads,
    )
    logger.set_stream_handler(stream_handler)
    logger.set_level(_logging.DEBUG if debug else _logging.INFO)
    logger.quiet = quiet
    logger.printshellcmds = printshellcmds


def success(message, title="Success", border_style="green", expand=True):
    """
    Helper function to print successful message.
    """
    print(
        Panel(
            f"[bold green] {message}[/bold green]",
            title=title,
            border_style=border_style,
            expand=expand,
        )
    )


def error(message, title="Error", border_style="red", expand=True):
    """
    Helper function to print error "beep boop" message.
    """
    print(
        Panel(
            f"[bold red] {message}[/bold red]",
            title=title,
            border_style=border_style,
            expand=expand,
        )
    )


def exit(message, title="Error", border_style="red", expand=True):
    error(message, title, border_style, expand)
    sys.exit(-1)


def warning(message, title="Warning", border_style="yellow"):
    """
    Helper function to print a warning
    """
    print(
        Panel(
            message,
            title=f"[yellow]{title}[/yellow]",
            border_style=border_style,
        )
    )
