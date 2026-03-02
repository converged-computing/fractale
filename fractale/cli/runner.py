from rich import print


def run_fractale(engine, args):
    """
    Shared function to run fractale between agent/prompt commands
    """
    result = None

    # Select interaction mode and attach UI
    try:
        if args.mode == "tui":
            from fractale.ui.adapters.tui import FractaleApp

            # The App takes ownership of the Engine.
            # It will instantiate TextualAdapter and assign it to engine.ui
            engine = FractaleApp(engine)

        elif args.mode == "web":
            from fractale.ui.adapters.web import WebAdapter

            engine.ui = WebAdapter(url="http://localhost:3000")

        # Run the engine
        result = engine.run()

    # Clean up or close database if relevant
    finally:
        if result is not None:
            print(result)
