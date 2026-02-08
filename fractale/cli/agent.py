from rich import print

from fractale.db import get_database
from fractale.engines import get_engine


def main(args, extra, **kwargs):
    """
    Run an agent workflow using the configured engine.
    """
    # Prepare Context from Arguments
    context = vars(args)
    result = None

    # Prepare a database for saving results (optional)
    database = get_database(args.database)
    if database:
        database.connect()

    # Instantiate the Engine (native state machine, autogen, langchain)
    engine = get_engine(
        engine=args.engine,
        plan=args.plan,
        backend=args.backend,
        max_attempts=args.max_attempts,
        database=database,
    )

    # Select interaction mode and attach UI
    try:
        if args.mode == "tui":
            from fractale.ui.adapters.tui import FractaleApp

            # The App takes ownership of the Engine.
            # It will instantiate TextualAdapter and assign it to engine.ui
            app = FractaleApp(engine, context)
            result = app.run()

        elif args.mode == "web":
            from fractale.ui.adapters.web import WebAdapter

            engine.ui = WebAdapter(url="http://localhost:3000")
            result = engine.run(context)

        else:
            from fractale.ui.adapters.cli import CLIAdapter

            engine.ui = CLIAdapter()
            result = engine.run(context)

    # Clean up or close database if relevant
    finally:
        if database:
            database.close()
        elif result is not None:
            print(result)
