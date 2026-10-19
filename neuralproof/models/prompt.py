"""Shared training and inference serialization for tactic prediction."""


def format_tactic_prompt(context: str, goal_state: str | tuple[str, ...] | list[str]) -> str:
    """Format only information available identically in mined and live states."""
    if isinstance(goal_state, (tuple, list)):
        goal_state = "\n".join(goal_state)
    return f"Context:\n{context}\nProof state:\n{goal_state}\nNext tactic:\n"
