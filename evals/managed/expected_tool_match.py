def evaluate(ctx: EvaluationContext) -> EvaluationResult:
    """Compare deterministic expected tool selection on experiment items."""
    expected_output = (
        ctx.experiment.item_expected_output if ctx.experiment is not None else None
    )
    expected_tool = (
        expected_output.get("tool") if isinstance(expected_output, dict) else None
    )
    output = ctx.observation.output
    calls = output.get("tool_calls", []) if isinstance(output, dict) else []
    actual_tools = [
        call.get("name")
        for call in calls
        if isinstance(call, dict) and isinstance(call.get("name"), str)
    ]
    matches = (
        not actual_tools if expected_tool is None else expected_tool in actual_tools
    )
    return EvaluationResult(
        scores=[
            Score(
                name="expected_tool_match",
                value=matches,
                data_type="BOOLEAN",
                comment=(
                    "Observed tool selection matches the dataset expectation."
                    if matches
                    else "Expected %r; observed %r." % (expected_tool, actual_tools)
                ),
                metadata={"expected_tool": expected_tool, "actual_tools": actual_tools},
            )
        ]
    )
