def evaluate(ctx: EvaluationContext) -> EvaluationResult:
    """Validate the privacy-safe summary stored on the root agent observation."""
    output = ctx.observation.output
    errors = []
    if not isinstance(output, dict):
        errors.append("output must be an object")
    else:
        if not isinstance(output.get("intent"), str):
            errors.append("intent must be a string")
        if not isinstance(output.get("text"), str):
            errors.append("text must be a string")
        for field_name in ("tool_names", "action_types"):
            value = output.get(field_name)
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                errors.append(field_name + " must be a list of strings")

    valid = not errors
    return EvaluationResult(
        scores=[
            Score(
                name="response_schema_valid",
                value=valid,
                data_type="BOOLEAN",
                comment=(
                    "Root observation follows agent.chat.summary.v1."
                    if valid
                    else "; ".join(errors)
                ),
                metadata={"contract": "agent.chat.summary.v1"},
            )
        ]
    )
