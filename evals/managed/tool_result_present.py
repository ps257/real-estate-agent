def evaluate(ctx: EvaluationContext) -> EvaluationResult:
    """Pass only for a completed, successful agent-side MCP call summary."""
    output = ctx.observation.output
    present = isinstance(output, dict) and output.get("status") == "ok"
    return EvaluationResult(
        scores=[
            Score(
                name="tool_result_present",
                value=present,
                data_type="BOOLEAN",
                comment=(
                    "MCP client observation has a successful result summary."
                    if present
                    else "MCP client observation is missing a successful result summary."
                ),
                metadata={"contract": "agent.mcp.result-summary.v1"},
            )
        ]
    )
