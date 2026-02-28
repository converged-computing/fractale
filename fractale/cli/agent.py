from fractale.core.plan import Plan
from fractale.engines import get_engine
from fractale.logger.logger import logger

from .runner import run_fractale


def main(args, extra, **kwargs):
    """
    Run an agent workflow using the configured engine.
    """
    # Instantiate the Engine (native state machine)
    engine = get_engine(
        engine=args.engine,
        backend=args.backend,
        max_attempts=args.max_attempts,
    )
    valid_names = set([x.name for x in engine.get_local_tools()])
    if args.agent not in valid_names:
        logger.exit(f"{args.agent} is not a known sub-agent.")

    prompt = " ".join(args.instruction)
    plan = Plan(
        {
            "name": "Agentic plan",
            "steps": [{"name": args.agent, "type": "plan", "inputs": {"goal": prompt}}],
        }
    )
    engine.plan = plan
    run_fractale(engine, args)
