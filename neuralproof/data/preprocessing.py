"""Prepare supervised tactic rows, excluding unvalidated InfoTree records."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from neuralproof.data.splits import split_for
from neuralproof.goal_state import goal_markers
from neuralproof.models.prompt import format_tactic_prompt

SPLITS = ("train", "validation", "test")
# Validation markers that mean the row was replayed by Lean.
REPLAYED = {"replayed", "declaration_replayed"}
# Targets that the InfoTree driver captured but that are not tactics: the
# `by` of a declaration header, the `where` of a structure instance, and
# the brace of a term.  They are recorded as parser nodes with a source span,
# but no tactic can answer them.
NON_TACTIC_TARGETS = {"by", "where"}


def is_tactic_target(target: str) -> bool:
    """True when the row's target is a tactic the model could produce.

    Every Lean tactic names something, so a target without a letter is a
    parser fragment or a placeholder (`{`, `(`, `‹_›`, `1`).  `by` and
    `where` are keywords of a declaration and of a structure instance, not
    tactics.
    """
    text = str(target).strip()
    if not text:
        return False
    if text in NON_TACTIC_TARGETS:
        return False
    return any(character.isalpha() for character in text)


@dataclass(frozen=True)
class PreparedDataset:
    """Processed rows plus the counts needed to audit how they were produced."""

    groups: dict[str, list[dict[str, Any]]]
    excluded_unvalidated: int = 0
    excluded_non_tactic_targets: int = 0
    split_disagreements: int = 0
    goal_scope_counts: dict[str, int] = field(default_factory=dict)
    validation_status_counts: dict[str, int] = field(default_factory=dict)
    split_seed: str = "neuralproof-v1"
    include_unvalidated: bool = False


def _is_conv_goal(goal_state: str) -> bool:
    """True for a `conv` subgoal, which Lean renders with `|` instead of `⊢`."""
    markers = goal_markers(goal_state)
    return bool(markers) and all(marker.startswith("| ") for marker in markers)


def _is_empty_state(state: str) -> bool:
    return state.strip() in ("", "no goals")


def _closed_its_focus(row: dict[str, Any]) -> bool:
    """True when the row's own result state is empty while the proof continues.

    A row without a `result_state` field carries no evidence about scope: the
    narrow extractor writes only the goal state it observed, so such a row is
    never labelled focus-local.
    """
    if "result_state" not in row:
        return False
    return _is_empty_state(str(row["result_state"]))


def classify_goal_scope(rows: list[dict[str, Any]]) -> list[str]:
    """Label each row's mined goal state as `proof`, `focus` or `conv`.

    The InfoTree driver reports the goals of the tactic's own focus, so a
    tactic inside a bullet or a `conv` block is mined with a state that the
    live client never shows: the live client always reports every open goal of
    the proof.  A row is labelled `focus` when its own result state is empty
    while its declaration continues, which can only happen inside a focus, and
    `conv` when its goal state carries a `conv` marker.  The last row of a
    declaration is labelled `proof` even when it may still be focus-scoped.
    """
    by_declaration: dict[tuple[str, str], list[int]] = {}
    for index, row in enumerate(rows):
        key = (str(row.get("source_file", "")), str(row.get("source_declaration", "")))
        by_declaration.setdefault(key, []).append(index)
    labels = ["proof"] * len(rows)
    for indexes in by_declaration.values():
        ordered = sorted(indexes, key=lambda i: (rows[i].get("source_start") or 0,
                                                 rows[i].get("source_end") or 0, i))
        last = ordered[-1] if ordered else -1
        for index in ordered:
            row = rows[index]
            if _is_conv_goal(str(row.get("goal_state", ""))):
                labels[index] = "conv"
            elif index != last and _closed_its_focus(row):
                labels[index] = "focus"
    return labels


def _validation_status(row: dict[str, Any]) -> str:
    """Whether the row was replayed by Lean, or only mined from an InfoTree.

    Rows without a `validation` marker come from the narrow extractor, which
    writes a row only after Lean replayed the tactic and the kernel accepted
    the resulting declaration, so they count as replayed.
    """
    validation = row.get("validation")
    if validation is None or validation in REPLAYED:
        return "replayed"
    return "unreplayed"


def prepare_dataset(rows: list[dict[str, Any]], *, seed: str = "neuralproof-v1",
                    include_unvalidated: bool = False) -> PreparedDataset:
    """Group rows by split, keeping the split the corpus already recorded.

    A row keeps the split assigned by the corpus that produced it; the seed is
    used only for rows that carry no split at all.  Rows whose recorded split
    disagrees with the seed are counted rather than silently re-split, so a
    corpus built with another seed cannot leak test files into training.

    Rows that were never replayed by Lean are excluded by default.  With
    `include_unvalidated` they are kept and stamped `validation_status:
    "unreplayed"`, so a dataset built from unreplayed contexts stays visible
    instead of passing as validated data.

    Rows whose target is not a tactic are excluded: the InfoTree driver
    records parser fragments such as the `by` of a declaration header as
    tactic nodes, and training on them teaches the model to answer with a
    keyword that closes no goal.
    """
    groups: dict[str, list[dict[str, Any]]] = {name: [] for name in SPLITS}
    excluded = 0
    excluded_targets = 0
    disagreements = 0
    scopes = classify_goal_scope(rows)
    scope_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for index, original in enumerate(rows):
        status = _validation_status(original)
        if status == "unreplayed" and not include_unvalidated:
            excluded += 1
            continue
        if not is_tactic_target(original.get("target_tactic", "")):
            excluded_targets += 1
            continue
        row = dict(original)
        source_file = str(row.get("source_file", ""))
        recorded = row.get("split")
        if recorded in groups:
            if split_for(source_file, seed) != recorded:
                disagreements += 1
            row["split"] = recorded
        else:
            row["split"] = split_for(source_file, seed)
        scope = scopes[index]
        row["goal_scope"] = scope
        scope_counts[scope] = scope_counts.get(scope, 0) + 1
        row["validation_status"] = status
        status_counts[status] = status_counts.get(status, 0) + 1
        row["prompt"] = format_tactic_prompt(row["context"], row["goal_state"])
        groups[row["split"]].append(row)
    return PreparedDataset(groups=groups, excluded_unvalidated=excluded,
                            excluded_non_tactic_targets=excluded_targets,
                            split_disagreements=disagreements,
                            goal_scope_counts=scope_counts,
                            validation_status_counts=status_counts, split_seed=seed,
                            include_unvalidated=include_unvalidated)


def prepare_rows(rows: list[dict[str, Any]], *, seed: str = "neuralproof-v1") -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Group training rows by split and omit explicitly pending/failed replays.

    Legacy rows without a `validation` field come from the narrow extractor,
    which only writes rows after successful Lean replay and kernel verification.
    InfoTree rows must carry a successful replay status to enter this dataset.
    """
    result = prepare_dataset(rows, seed=seed)
    return result.groups, result.excluded_unvalidated
