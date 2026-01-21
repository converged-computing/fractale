import jsonschema
from jsonschema import validators


def set_defaults(validator, properties, instance, schema):
    for prop, sub_schema in properties.items():
        if "default" in sub_schema:
            instance.setdefault(prop, sub_schema["default"])


plan_validator = validators.extend(
    jsonschema.Draft7Validator,
    {"properties": set_defaults},
)

plan_schema = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "inputs": {"type": "object", "default": {}},
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ["agent", "tool"], "default": "agent"},
                    # Agent specific
                    "prompt": {"type": "string"},
                    # Tool specific
                    "tool": {"type": "string"},
                    "allow_tools": {"type": "boolean", "default": True},
                    "description": {"type": "string"},
                    "args": {"type": "object"},
                    "inputs": {"type": "object", "additionalProperties": True},
                    # FSM Transitions
                    "transitions": {
                        "type": "object",
                        "properties": {
                            "success": {"type": "string"},
                            "failure": {"type": "string"},
                        },
                        "additionalProperties": True,
                    },
                },
                "required": ["name"],
            },
        },
    },
    "required": ["name"],
}


def validate_plan(data):
    validator = plan_validator(plan_schema)
    try:
        validator.validate(data)
    except Exception as e:
        raise ValueError(f"❌ Plan YAML invalid: {e}!")
