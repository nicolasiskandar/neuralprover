"""The retrieval evaluation helpers: query normalization and name matching.

These cases pin the protocol decisions that the report depends on: the goal
target is the primary query, inaccessible-name markers are not terms, and
local or out-of-corpus references are not counted as retrieval failures.
"""
import importlib.util
from pathlib import Path

import pytest

from neuralproof.retrieval import BM25Index

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_evaluator():
    path = REPO_ROOT / "scripts" / "evaluate_retrieval.py"
    spec = importlib.util.spec_from_file_location("evaluate_retrieval", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


evaluator = _load_evaluator()


def test_normalize_query_drops_inaccessible_markers_and_case_labels():
    goal = "\ncase succ\nx✝¹ : ℕ\nh✝ : True\n⊢ x✝ = 1"
    assert evaluator._normalize_query(goal) == "x : ℕ\nh : True\n⊢ x = 1"


def test_goal_target_is_the_expression_after_the_turnstile():
    goal = "x : ℕ\n⊢ x + 0 = x"
    assert evaluator._goal_target(goal) == "x + 0 = x"
    assert evaluator._goal_target("no turnstile") == "no turnstile"


def test_global_references_exclude_locals_and_resolve_suffixes():
    index = {"Mathlib.Foo.bar", "bar", "Baz.qux", "qux"}
    allowed = frozenset({"x", "Mathlib"})
    assert not evaluator.is_global_reference("x", index, allowed)
    assert not evaluator.is_global_reference("Mathlib.Foo.bar", index, allowed)
    assert evaluator.is_global_reference("Mathlib.Foo.bar", index, frozenset({"x"}))
    assert evaluator.is_global_reference("bar", index, frozenset({"x"}))
    assert evaluator.is_global_reference("Foo.bar", index, frozenset({"x"}))
    assert not evaluator.is_global_reference("missing", index, allowed)


def test_name_matcher_contains_exact_basename_and_suffix():
    matcher = evaluator.NameMatcher(["Mathlib.Foo.bar", "Baz.qux"])
    assert matcher.contains("Mathlib.Foo.bar")
    assert matcher.contains("Foo.bar")
    assert matcher.contains("bar")
    assert matcher.contains("qux")
    assert not matcher.contains("missing")


def test_name_matcher_strict_and_relaxed_suffix_rules():
    assert evaluator.NameMatcher.matches(
        "Mathlib.Foo.bar", "Foo.bar", strict=True)
    assert evaluator.NameMatcher.matches(
        "Foo.bar", "Mathlib.Foo.bar", strict=True)
    assert evaluator.NameMatcher.matches(
        "Mathlib.Foo.bar", "Other.bar", strict=False)
    assert not evaluator.NameMatcher.matches(
        "Mathlib.Foo.bar", "Other.bar", strict=True)


@pytest.mark.parametrize(("target", "syntax_kind", "expected"), [
    ("rw [foo]", "", "rw"),
    ("Prod.isUnit_iff", "Lean.Parser.Tactic.simp", "simp"),
    ("Foo.bar", "Lean.Parser.Tactic.allGoals", "all_goals"),
    ("Foo.bar", "Lean.Parser.Tactic.tacticRfl", "rfl"),
    ("Contact", "", "Contact"),
])
def test_target_family_uses_the_enclosing_tactic_for_bare_arguments(
        target, syntax_kind, expected):
    assert evaluator.target_family(target, syntax_kind) == expected


def _index():
    index = BM25Index()
    index.add("Foo.sum_comm", "sum comm")
    index.add("Foo.sum_assoc", "sum assoc")
    index.add("Bar.prod_comm", "prod comm")
    # Filler documents raise the corpus size so the default max-df filter keeps
    # ``sum`` (which occurs in two real candidates).  They share no query term.
    for number in range(17):
        index.add(f"Filler.n{number}", "unrelated filler")
    return index.finalize()


def _row(example_id, gold, query="sum assoc"):
    return {
        "row": {
            "example_id": example_id,
            "source_declaration": "Foo.sum_comm",
            "source_file": "Mathlib/Foo.lean",
        },
        "family": "rw",
        "query": query,
        "goal_target": query,
        "target_module": "Mathlib.Foo",
        "gold": gold,
        "local": [],
    }


def test_evaluate_reports_row_and_reference_hits():
    rows = evaluator.evaluate(
        [_row("ex", ["sum_assoc"])], _index(), evaluator.NameMatcher([]), {},
        exclude_module=False)
    row = rows[0]
    assert row["row_hit"] == {1: True, 5: True, 10: True, 20: True}
    assert row["reference_hits"] == {1: 1, 5: 1, 10: 1, 20: 1}
    assert row["strict_row_hit"][1] is True


def test_evaluate_can_exclude_the_targets_own_module():
    module_names = {"Mathlib.Foo": {"Foo.sum_comm", "Foo.sum_assoc"}}
    without_exclusion = evaluator.evaluate(
        [_row("ex", ["prod_comm"], query="sum assoc prod")], _index(),
        evaluator.NameMatcher([]), {}, exclude_module=False)
    with_exclusion = evaluator.evaluate(
        [_row("ex", ["prod_comm"], query="sum assoc prod")], _index(),
        evaluator.NameMatcher([]), module_names, exclude_module=True)

    assert without_exclusion[0]["row_hit"][1] is False
    assert with_exclusion[0]["row_hit"][1] is True


def test_summarize_counts_rows_and_references():
    rows = [
        {**_row("a", ["sum_assoc"]), "row_hit": {1: True, 5: True, 10: True, 20: True},
         "reference_hits": {1: 1, 5: 1, 10: 1, 20: 1},
         "strict_row_hit": {1: True, 5: True, 10: True, 20: True}},
        {**_row("b", ["missing"]), "row_hit": {1: False, 5: False, 10: False, 20: False},
         "reference_hits": {1: 0, 5: 0, 10: 0, 20: 0},
         "strict_row_hit": {1: False, 5: False, 10: False, 20: False}},
    ]
    summary = evaluator.summarize(rows)
    assert summary["applicable_rows"] == 2
    assert summary["gold_references"] == 2
    assert summary["recall_rows"]["1"] == pytest.approx(0.5)
    assert summary["recall_references"]["1"] == pytest.approx(0.5)
    assert summary["by_family"]["rw"]["rows"] == 2
