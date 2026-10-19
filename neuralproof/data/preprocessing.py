"""Prepare supervised tactic rows, excluding unvalidated InfoTree records."""
from __future__ import annotations

from typing import Any

from neuralproof.data.splits import split_for
from neuralproof.models.prompt import format_tactic_prompt


def prepare_rows(rows: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Group training rows by split and omit explicitly pending/failed replays.

    Legacy rows without a `validation` field come from the narrow extractor,
    which only writes rows after successful Lean replay and kernel verification.
    InfoTree rows must carry a successful replay status to enter this dataset.
    """
    groups: dict[str, list[dict[str, Any]]] = {k: [] for k in ("train", "validation", "test")}
    excluded = 0
    for original in rows:
        validation = original.get("validation")
        if validation is not None and validation not in {"replayed", "declaration_replayed"}:
            excluded += 1
            continue
        row = dict(original)
        row["split"] = split_for(row["source_file"])
        row["prompt"] = format_tactic_prompt(row["context"], row["goal_state"])
        groups[row["split"]].append(row)
    return groups, excluded
