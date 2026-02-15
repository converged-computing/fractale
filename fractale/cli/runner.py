from rich import print


def run_fractale(engine, mode, database):
    """
    Shared function to run fractale between agent/prompt commands
    """
    result = None

    # Select interaction mode and attach UI
    try:
        if mode == "tui":
            from fractale.ui.adapters.tui import FractaleApp

            # The App takes ownership of the Engine.
            # It will instantiate TextualAdapter and assign it to engine.ui
            app = FractaleApp(engine)
            result = app.run()

        elif mode == "web":
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
