from fractale.db import get_database
from fractale.engines import get_engine

from .runner import run_fractale


def main(args, extra, **kwargs):
    """
    Run an agent workflow using the configured engine.
    """
    # Prepare a database for saving results (optional)
    database = get_database(args.database)
    if database:
        database.connect()

    # Instantiate the Engine (native state machine)
    engine = get_engine(
        engine=args.engine,
        plan=args.plan,
        backend=args.backend,
        max_attempts=args.max_attempts,
        database=database,
    )
    run_fractale(engine, args.mode, database)
