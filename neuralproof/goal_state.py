"""Canonical goal-state rendering shared by mined corpora and live Lean runs.

The InfoTree driver renders goals with `ppGoals ... .pretty`; a live Lean run
renders them with `trace_state`.  Both go through the same elaborator
renderer, so the two texts agree byte for byte except for the leading blank
line that `ppGoals` emits for a goal whose local context is empty.  Every
consumer therefore passes through `canonical_goal_state`, which makes mined
and live prompts identical instead of differing by one character.
"""
from __future__ import annotations

import re

# `case <name>` precedes the local context of every goal that carries a case name.
CASE_HEADER = re.compile(r"^case\s+\S+\s*$")
# `⊢` for ordinary goals, `|` for goals created in `conv` mode.
GOAL_MARKER = re.compile(r"^(?:⊢|\|) ")


def canonical_goal_state(text: str) -> str:
    """Normalize a goal rendering to the single form used for prompts."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip("\n")


def goal_markers(text: str) -> tuple[str, ...]:
    """Return the goal lines of a rendering, one per open goal."""
    return tuple(line for line in canonical_goal_state(text).split("\n") if GOAL_MARKER.match(line))


def goal_count(text: str) -> int:
    """Number of open goals in a rendering."""
    return len(goal_markers(text))


def split_goal_blocks(text: str) -> tuple[str, ...]:
    """Split a goal rendering into one block per open goal.

    Lean prints `case <name>` before the local context of every goal that has
    a case name, and that is the only unambiguous boundary in the rendering.
    Several goals can share one case header, so a block may hold more than one
    goal: 82 of the 218 mined Mathlib rows with more than one goal group them
    that way.  The mined and the live renderings are split by this same
    function, so the two stay comparable.  Use `goal_count` when the exact
    number of open goals is required.
    """
    canonical = canonical_goal_state(text)
    if not canonical:
        return ()
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in canonical.split("\n"):
        if CASE_HEADER.match(line) and any(GOAL_MARKER.match(item) for item in current):
            blocks.append(current)
            current = []
        current.append(line)
    blocks.append(current)
    return tuple("\n".join(block) for block in blocks)
