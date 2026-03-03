import os

from fractale.core.plan import Plan


def get_engine(
    plan=None, engine="native", backend="gemini", ui=None, max_attempts=100, database=None
):
    """
    Get the fractale engine! 🚘

    This is new, and could allow us to support different orchestators. We previously had LangChain
    and AutoGen here, but I cannot (do not want) to focus development on three different engines at once.
    """
    # This is loading the plan path
    if plan is not None:
        plan = Plan(plan)

    # State machine orchestration
    if engine == "native":
        from fractale.engines.native.engine import Manager
    else:
        raise ValueError(f"Engine {engine} is not recognized.")
    return Manager(plan=plan, ui=ui, max_attempts=max_attempts, database=database)
