def evaluate(ctx: EvaluationContext) -> EvaluationResult:
    """Pass when the root agent observation contains a user-visible result."""
    output = ctx.observation.output
    if isinstance(output, str):
        present = bool(output.strip())
    elif isinstance(output, dict):
        text = output.get("text")
        actions = output.get("action_types")
        present = bool(isinstance(text, str) and text.strip()) or bool(
            isinstance(actions, list) and actions
        )
    else:
        present = output is not None

    return EvaluationResult(
        scores=[
            Score(
                name="agent_output_present",
                value=present,
                data_type="BOOLEAN",
                comment=(
                    "Agent returned text or a structured UI action."
                    if present
                    else "Agent output has neither non-empty text nor a UI action."
                ),
                metadata={"contract": "agent.chat.summary.v1"},
            )
        ]
    )
