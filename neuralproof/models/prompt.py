"""Shared training and inference serialization for tactic prediction."""
from neuralproof.goal_state import canonical_goal_state


def format_tactic_prompt(context: str, goal_state: str | tuple[str, ...] | list[str]) -> str:
    """Format only information available identically in mined and live states.

    The goal state is canonicalized so that a mined corpus row and a live Lean
    run produce the same prompt: the mined rendering starts with a blank line
    that the live rendering does not.
    """
    if isinstance(goal_state, (tuple, list)):
        goal_state = "\n".join(goal_state)
    return f"Context:\n{context}\nProof state:\n{canonical_goal_state(goal_state)}\nNext tactic:\n"
