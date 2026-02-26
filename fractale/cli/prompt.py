from fractale.core.plan import Plan
from fractale.engines import get_engine

from .runner import run_fractale


def main(args, extra, **kwargs):
    """
    Run an agent workflow using the configured engine.
    """
    # Instantiate the Engine without a plan
    engine = get_engine(
        engine=args.engine,
        backend=args.backend,
        max_attempts=args.max_attempts,
    )
    # Define the plan from the instruction
    prompt = " ".join(args.instruction)
    plan = Plan(
        {
            "name": "Agentic plan",
            "steps": [{"name": "ask", "type": "tool", "inputs": {"goal": prompt}}],
        }
    )
    engine.plan = plan
    run_fractale(engine, args)
