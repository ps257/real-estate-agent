TOOL_CONTRACTS = __TOOL_CONTRACTS__


def _matches_type(value, expected):
    nullable = expected.endswith("?")
    kind = expected[:-1] if nullable else expected
    if value is None:
        return nullable
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string[]":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return False


def evaluate(ctx: EvaluationContext) -> EvaluationResult:
    """Validate agent-side MCP arguments against the exported FastMCP registry."""
    metadata = ctx.observation.metadata
    metadata = metadata if isinstance(metadata, dict) else {}
    tool_name = metadata.get("tool_name")
    arguments = ctx.observation.input
    contract = TOOL_CONTRACTS.get(tool_name)
    errors = []

    if contract is None:
        errors.append("unknown tool")
    elif not isinstance(arguments, dict):
        errors.append("arguments must be an object")
    else:
        properties = contract["properties"]
        missing = [key for key in contract["required"] if key not in arguments]
        unknown = [key for key in arguments if key not in properties]
        invalid = [
            key
            for key, value in arguments.items()
            if key in properties and not _matches_type(value, properties[key])
        ]
        if missing:
            errors.append("missing: " + ", ".join(sorted(missing)))
        if unknown:
            errors.append("unknown: " + ", ".join(sorted(unknown)))
        if invalid:
            errors.append("invalid type: " + ", ".join(sorted(invalid)))

    valid = not errors
    return EvaluationResult(
        scores=[
            Score(
                name="tool_call_valid",
                value=valid,
                data_type="BOOLEAN",
                comment=(
                    "Tool arguments match the exported FastMCP contract."
                    if valid
                    else "; ".join(errors)
                ),
                metadata={"tool_name": tool_name, "contract": "fastmcp.registry.v1"},
            )
        ]
    )
