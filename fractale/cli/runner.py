from rich import print

import fractale.core.registry as registry
from fractale.db import get_database


def run_fractale(engine, args):
    """
    Shared function to run fractale between agent/prompt commands
    """
    # Prepare a database for saving results (optional)
    database = get_database(args.database)
    if database:
        database.connect()

    result = None

    # Extra tools, resources, prompts, (capabilities) etc.
    registry.LocalToolRegistry.load_registries(args.registry or [])

    # Select interaction mode and attach UI
    try:
        if args.mode == "tui":
            from fractale.ui.adapters.tui import FractaleApp

            # The App takes ownership of the Engine.
            # It will instantiate TextualAdapter and assign it to engine.ui
            app = FractaleApp(engine)
            result = app.run()

        elif args.mode == "web":
            from fractale.ui.adapters.web import WebAdapter

            engine.ui = WebAdapter(url="http://localhost:3000")
            result = engine.run()

        else:
            from fractale.ui.adapters.cli import CLIAdapter

            engine.ui = CLIAdapter()
            result = engine.run()

    # Clean up or close database if relevant
    finally:
        if database:
            database.close()
        elif result is not None:
            print(result)
