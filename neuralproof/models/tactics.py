"""Extraction of a tactic from a model's raw completion.

A base language model continues the prompt as a document, so a completion
often starts by echoing the prompt back: the local context of the goal, the
goal marker, a `case` header, or the prompt's own labels.  The tactic the
model meant to write is the first line that is not such an echo.

The filter here is a budget saver, not a correctness claim: a line that
passes it is still only a candidate, and Lean remains the authority on
whether it is a valid tactic.
"""
from __future__ import annotations

import re

# Labels the prompt itself uses.  A completion that starts with one of them
# is continuing the document, not answering it.
PROMPT_LABELS = ("context:", "proof state:", "next tactic:", "tactic:")

# `case <name>` introduces the local context of a goal.
CASE_HEADER = re.compile(r"^case\s+\S+\s*$")

# A local-context line: `x : Nat`, `inst✝ : AddMonoid G`, `h : p`.
BINDER = re.compile(r"^\S+\s*:\s*\S")

# The goal marker of a rendering: `⊢ goal` or `| conv goal`.
GOAL_MARKER = re.compile(r"^(?:⊢|\|)\s")


def _is_echo(line: str) -> bool:
    """True when the line is part of the prompt rather than a tactic."""
    stripped = line.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    if lowered in PROMPT_LABELS:
        return True
    if CASE_HEADER.match(stripped):
        return True
    if GOAL_MARKER.match(stripped):
        return True
    if BINDER.match(stripped):
        return True
    return False


def extract_tactic(completion: str) -> str:
    """The first plausible tactic line of a completion, or `""` if there is none.

    The completion is scanned line by line and the first line that is not an
    echo of the prompt is returned.  A leading blank line is skipped, so a
    model that mirrors the prompt's blank line still yields its answer.
    """
    for line in completion.splitlines():
        if _is_echo(line):
            continue
        return line.strip()
    return ""
