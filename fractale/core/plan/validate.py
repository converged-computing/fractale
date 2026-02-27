import re

# We want to find the output references in jinja2
jinja_pattern = re.compile(r"steps\.(?P<step_name>[^.]+)\.outputs\.(?P<output_key>[^} ]+)")


class StepsValidator:
    """
    A StepsValidator is a helper class to validate steps.
    """

    def __init__(self, steps):
        self.set_steps(steps)

    def set_steps(self, steps):
        """
        set_steps allows for update the class steps after.
        """
        self.steps = steps
        # Save output schema lookups so we can evaluate jinja2 outputs
        self.output_schemas = {
            s["name"]: s["schema"].get("outputSchema", {}) for s in steps if s.get("name")
        }
        self.input_schemas = {
            s["name"]: s["schema"].get("inputSchema", {}) for s in steps if s.get("name")
        }
        self.valid_names = set(x.get("name") for x in steps if x.get("name"))

    def validate(self, required_annotation=None):
        """
        Ensure that the agent does not request a tool or prompt that does not exist.

        We allow each modular function to define and return errors so they could
        theoretically be called indepdently.
        """
        # A validation resets errors. We will return errors, and reset again
        errors = []
        for i, step in enumerate(self.steps):
            errors += self.validate_step(i, step, required_annotation)

        # Return errors if we have them!
        if errors:
            return "\n".join(errors)

    def validate_step(self, i, step, required_annotation=None):
        """
        Validate a single step.
        """
        errors = []
        # Don't continue beyond here, we need the name
        if "name" not in step:
            errors.append(f"Step at index {i} is missing a 'name'")
            return errors

        # Do we have required annotations?
        errors += self.validate_annotations(step, required_annotation)

        # Are the transitions valid?
        errors += self.validate_transitions(step)

        # Outputs (inputs to  other steps) validation
        errors += self.validate_step_inputs(step)
        return errors

    def validate_annotations(self, step, required_annotation=None):
        """
        Validate that an annotation (dict) is present.
        """
        errors = []
        input_schema = step["schema"].get("input_schema") or {}

        if not required_annotation:
            return errors
        for key, value in required_annotation.items():
            if key not in input_schema.get("annotations", {}):
                errors.append(f"Step {step.name} is missing required annotation {key}: {value}")
                continue
            found_value = input_schema["annotations"][key]
            if found_value != value:
                errors.append(
                    f"Step {step.name} has incorrect annotation value for {key}. Want {value} found {found_value}"
                )
        return errors

    def validate_transitions(self, step):
        """
        Validate that step transitions are in success / failure
        """
        errors = []
        step_name = step["name"]
        for state, transition in step.get("transitions", {}).items():
            if state not in ["success", "failure"]:
                errors.append(
                    f"Step {step_name} has a transition name not in 'success' or 'failure' and is invalid."
                )
            if transition not in self.valid_names:
                errors.append(
                    f"Transition for step {step_name} given '{state}' is not known. Known are: {self.valid_names}"
                )
        return errors

    def validate_calls(self, step):
        """
        Validate calls (capabilities, calls like prmopts and tools)
        """
        errors = []
        # Prompt and tool validation
        if "prompt" in step:
            if step["prompt"] not in self.prompt_map:
                errors.append(f"Agent requested prompt that does not exist: {step['prompt']}")
        elif "tool" in step:
            if step["tool"] not in self.tool_map:
                errors.append(f"Agent requested tool that does not exist: {step['tool']}")
        return errors

    def validate_step_inputs(self, step):
        """
        Validate step inputs
        """
        errors = []
        inputs = step.get("inputs") or {}
        step_name = step["name"]
        for key, value in inputs.items():
            if not isinstance(value, str) or "{{" not in value:
                continue
            for match in jinja_pattern.finditer(value):
                found_step = match.group("step_name")
                raw_output_expression = match.group("output_key").strip()

                # The agent sometimes adds Python method syntax: e.g., lines.join('\n')
                if "(" in raw_output_expression or ")" in raw_output_expression:
                    errors.append(
                        f"Step '{step_name}': Input '{key}' uses invalid Python method syntax: '{raw_output_expression}'. "
                        f"Use Jinja2 filters (e.g., '| join') instead of methods (e.g., '.join()')."
                    )

                # Extract base key for schema validation (e.g., 'lines' from 'lines.join' or 'lines|upper')
                found_value = re.split(r"[\.|\|]", raw_output_expression)[0]
                if found_step not in self.valid_names:
                    errors.append(
                        f"Step '{step_name}': Input '{key}' references unknown step '{found_step}'"
                    )

                # Now we need to make sure the found value is an actual output
                out_schema = self.output_schemas.get(found_step)

                # It's probably ok to not define an output
                if not out_schema:
                    continue

                properties = out_schema.get("properties", {})
                is_wrapped = out_schema.get("x-fastmcp-wrap-result", False)

                # Check if the key is in the schema's properties
                if properties and found_value not in properties:
                    # FastMCP often wraps everything in a result key
                    if is_wrapped and found_value == "result":
                        continue
                    errors.append(
                        f"Step '{step_name}': Input '{key}' expects output '{found_value}' "
                        f"from '{found_step}', but that tool only provides: {list(properties.keys())}"
                    )
        return errors
