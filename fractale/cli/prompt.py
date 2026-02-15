from fractale.core.plan import Plan
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

    # Instantiate the Engine without a plan
    engine = get_engine(
        engine=args.engine,
        backend=args.backend,
        max_attempts=args.max_attempts,
        database=database,
    )
    # Define the plan from the instruction
    prompt = " ".join(args.instruction)
    plan = Plan(
        {
            "name": "Agentic plan",
            "steps": [{"name": "planner", "type": "plan", "instruction": prompt}],
        }
    )
    engine.plan = plan
    run_fractale(engine, args.mode, database)
