import logging

from jinja2 import BaseLoader, Environment

logger = logging.getLogger(__name__)


def resolve_templates(inputs: dict, context: dict, schema: set) -> dict:
    """
    Resolves Jinja2 templates and populates function arguments based on a schema.
    1. Priority to explicit inputs (resolved via Jinja).
    2. Fallback to context for missing schema keys.
    3. Filter out any keys not in the schema.
    """
    # Normalize inputs and context
    inputs = inputs or {}
    context_data = getattr(context, "data", context)

    env = Environment(loader=BaseLoader())
    final_inputs = {}

    # Resolve provided inputs first (Jinja resolution)
    resolved_user_inputs = {}
    for k, v in inputs.items():
        if isinstance(v, str) and "{{" in v:
            try:
                resolved_user_inputs[k] = env.from_string(v).render(**context_data)
            except Exception as e:
                logger.warning(f"Jinja render failed for key '{k}': {e}")
                resolved_user_inputs[k] = v
        else:
            resolved_user_inputs[k] = v

    # Reconcile with Schema
    # We only care about keys the function actually accepts
    for arg in schema:
        if arg in resolved_user_inputs:
            # Plan provided it, so use it
            final_inputs[arg] = resolved_user_inputs[arg]
        elif arg in context_data:
            # Plan didn't provide it, but it's in the global context
            final_inputs[arg] = context_data[arg]
        else:
            # Not in inputs or context - skip it (or set a default if desired)
            continue

    return final_inputs
