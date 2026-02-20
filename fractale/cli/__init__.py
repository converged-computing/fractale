#!/usr/bin/env python

import argparse
import os
import sys

# This will pretty print all exceptions in rich
from rich.traceback import install

install()

import fractale
import fractale.agents as agents
import fractale.core.registry as registry
from fractale.logger import setup_logger


def get_parser():
    parser = argparse.ArgumentParser(
        description="Fractale",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # Global Variables
    parser.add_argument(
        "--debug",
        dest="debug",
        help="use verbose logging to debug.",
        default=False,
        action="store_true",
    )

    parser.add_argument(
        "--quiet",
        dest="quiet",
        help="suppress additional output.",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "--config-dir",
        dest="config_dir",
        help="Fractale configuration directory to store subsystems. Defaults to ~/.fractale",
    )
    parser.add_argument(
        "--version",
        dest="version",
        help="show software version.",
        default=False,
        action="store_true",
    )

    subparsers = parser.add_subparsers(
        help="actions",
        title="actions",
        description="actions",
        dest="command",
    )
    subparsers.add_parser("version", description="show software version")

    # Run an agent
    agent = subparsers.add_parser(
        "agent",
        formatter_class=argparse.RawTextHelpFormatter,
        description="run an agent",
    )
    agent.add_argument(
        "plan",
        help="provide a plan to a manager",
    )
    prompt = subparsers.add_parser(
        "prompt",
        formatter_class=argparse.RawTextHelpFormatter,
        description="run an agent",
    )
    prompt.add_argument(
        "instruction", help="provide a prompt instruction to the manager", nargs="*"
    )

    # Agent and prompt take the same inputs
    for command in [agent, prompt]:
        command.add_argument("--mode", choices=["cli", "tui", "web"], default="cli")
        command.add_argument(
            "--engine", choices=["native", "langchain", "autogen"], default="native"
        )
        command.add_argument("--backend", choices=["openai", "gemini", "llama"], default="gemini")
        command.add_argument("-r", "--registry", action="append", default=None)
        command.add_argument(
            "--database", help="URI for result storage (file://path or sqlite://path)"
        )
        command.add_argument(
            "--max-attempts",
            help="Maximum attempts for a manager or individual agent",
            default=None,
            type=int,
        )
    return parser


def run_fractale():
    """
    this is the main entrypoint.
    """
    parser = get_parser()

    def help(return_code=0):
        version = fractale.__version__

        print("\nFractale v%s" % version)
        parser.print_help()
        sys.exit(return_code)

    # If the user didn't provide any arguments, show the full help
    if len(sys.argv) == 1:
        help()

    # If an error occurs while parsing the arguments, the interpreter will exit with value 2
    args, extra = parser.parse_known_args()

    # Config discovers from environment
    os.environ["FRACTALE_LLM_PROVIDER"] = args.backend

    # Extra tools, resources, prompts, (capabilities) etc.
    registry.init_registry(args.registry or [])
    agents.init_backend()

    if args.debug is True:
        os.environ["MESSAGELEVEL"] = "DEBUG"

    # Show the version and exit
    if args.command == "version" or args.version:
        print(fractale.__version__)
        sys.exit(0)

    setup_logger(quiet=args.quiet, debug=args.debug)

    # Here we can assume instantiated to get args
    if args.command == "agent":
        from .agent import main
    elif args.command == "prompt":
        from .prompt import main
    else:
        help(1)
    main(args, extra)


if __name__ == "__main__":
    run_fractale()
