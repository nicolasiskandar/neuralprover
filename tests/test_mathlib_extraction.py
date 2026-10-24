"""The narrow Mathlib extractor: the context it builds and the failures it keeps."""
import pytest

from neuralproof.data.extraction import (MATHLIB_REVISION, _active_context, _source_imports,
                                         extract_mathlib_file)
from neuralproof.data.info_tree import trace_file
from neuralproof.data.normalize_info_tree import normalize_trace, validate_trace_examples
from neuralproof.lean.client import LeanClient

SAMPLE = "lean/NeuralProof/Samples.lean"


@pytest.fixture(scope="module")
def mathlib_root():
    from pathlib import Path
    root = Path(__file__).parents[1] / "lean/.lake/packages/mathlib"
    if not root.exists():
        pytest.skip("the pinned Mathlib checkout is not available")
    return root


# --- the context the extractor builds ---------------------------------------

def test_the_context_starts_from_the_source_imports():
    lines = ["import Mathlib", "import Mathlib.Data.Nat.Basic", "", "open scoped BigOperators"]
    assert _source_imports(lines, 3) == ["import Mathlib", "import Mathlib.Data.Nat.Basic"]


def test_the_context_uses_the_source_imports_and_not_a_blanket_mathlib():
    # Importing the module under extraction would import the theorem being
    # mined and leak its proof into the candidate environment, so the
    # context is built from the file's own imports.
    lines = ["import Mathlib.Data.Nat.Basic", "import Mathlib.Data.List.Basic"]
    imports = _source_imports(lines, 2)
    assert imports == ["import Mathlib.Data.Nat.Basic", "import Mathlib.Data.List.Basic"]
    context = _active_context(lines, 2, imports)
    assert context == "\n".join(imports)
    assert "import Mathlib\n" not in context


def test_the_context_keeps_the_active_namespace_and_opening():
    lines = ["import Mathlib", "namespace Nat", "open Function", "variable (n : Nat)"]
    context = _active_context(lines, 3, ["import Mathlib"])
    assert "namespace Nat" in context
    assert "open Function" in context
    assert "import Mathlib" in context


def test_a_closed_namespace_leaves_the_context():
    lines = ["import Mathlib", "namespace Nat", "open Function", "end Nat", "open Nat"]
    context = _active_context(lines, 5, ["import Mathlib"])
    assert "namespace Nat" not in context
    assert "open Nat" in context


def test_a_section_is_closed_by_a_bare_end():
    lines = ["import Mathlib", "section", "open Function", "end", "open Later"]
    context = _active_context(lines, 5, ["import Mathlib"])
    assert "section" not in context
    assert "open Later" in context


# --- the native driver -----------------------------------------------------

@pytest.mark.lean
def test_native_info_tree_driver_captures_goals():
    from pathlib import Path
    source = Path(__file__).parents[1] / SAMPLE
    result = trace_file(source, timeout=120)
    assert result["backend"] == "lean4_info_tree"
    assert result["tactic_nodes"] > 0
    assert any("n + 0 = n" in trace["goal_state"] for trace in result["traces"])
    assert result["command_nodes"] > 0
    assert any(command["syntax_kind"] == "Lean.Parser.Command.declaration"
               for command in result["commands"])


@pytest.mark.lean
def test_info_tree_normalizer_deduplicates_wrappers_and_tracks_steps():
    from pathlib import Path
    source = Path(__file__).parents[1] / SAMPLE
    trace = trace_file(source, timeout=120)
    rows, stats = normalize_trace(trace, source)
    assert stats["output_examples"] == 5
    assert [row["target_tactic"].splitlines()[0] for row in rows] == \
        ["trivial", "rfl", "constructor", "exact hp", "exact hq"]
    assert [row["source_declaration"] for row in rows] == \
        ["np_true", "np_add_zero", "np_pair", "np_pair", "np_pair"]
    assert all(row["goal_state"].strip() for row in rows)
    assert all(row["context"].startswith("import Lean") for row in rows)
    assert stats["deduplicated_nodes"] > 0


@pytest.mark.lean
def test_sample_trajectory_prefixes_replay_with_lean():
    from pathlib import Path
    source = Path(__file__).parents[1] / SAMPLE
    trace = trace_file(source, timeout=120)
    rows, _ = normalize_trace(trace, source)
    checked, stats = validate_trace_examples(trace, source, rows, timeout=60)
    assert len(checked) == 5
    assert stats["declarations_count"] == 3
    assert stats["validation_counts"] == {"replayed": 3}
    assert all(row["validation"] == "replayed" for row in checked)
    assert all(row["validation_harness_contains_sorry"] for row in checked)


@pytest.mark.lean
def test_real_mathlib_tactic_is_replayed_and_verified(mathlib_root):
    rows, stats = extract_mathlib_file(LeanClient(), mathlib_root,
                                       "Mathlib/Data/Nat/Basic.lean", limit=3)
    assert stats["source_revision"] == MATHLIB_REVISION
    assert len(rows) == 1
    assert {row["source_declaration"] for row in rows} == {"Nat.div_right_comm"}
    assert "namespace Nat" in rows[0]["context"]
    assert "open Function" in rows[0]["context"]
    assert "Mathlib.Data.Nat" in rows[0]["context"]
    assert "import Mathlib\n" not in rows[0]["context"]
    assert rows[0]["theorem_id"] == "np_mined_Mathlib_Data_Nat_Basic_Nat_div_right_comm"
    assert rows[0]["target_tactic"] == \
        "rw [Nat.div_div_eq_div_mul, Nat.mul_comm, ← Nat.div_div_eq_div_mul]"


@pytest.mark.lean
def test_info_tree_normalizer_keeps_source_rewrite_and_pre_tactic_state(mathlib_root):
    source = mathlib_root / "Mathlib/Data/Nat/Basic.lean"
    trace = trace_file(source, timeout=120)
    rows, _ = normalize_trace(trace, source)
    row = next(row for row in rows if row["source_declaration"] == "Nat.div_right_comm")
    assert row["target_tactic"] == \
        "rw [Nat.div_div_eq_div_mul, Nat.mul_comm, ← Nat.div_div_eq_div_mul]"
    assert row["syntax_kind"] == "Lean.Parser.Tactic.rewriteSeq"
    assert "a / b / c" in row["goal_state"]
    assert row["source_line"] == 59
    assert "import Mathlib\n" not in row["context"]


@pytest.mark.lean
def test_missing_prior_declaration_context_is_reported(mathlib_root):
    moved, moved_stats = extract_mathlib_file(LeanClient(), mathlib_root,
                                               "Mathlib/Algebra/MvPolynomial/Basic.lean", 1,
                                               "notMem_support_iff")
    group, group_stats = extract_mathlib_file(LeanClient(), mathlib_root,
                                              "Mathlib/Algebra/Group/Basic.lean", 1,
                                              "mul_div_mul_left_eq_div")
    assert (len(moved), len(group)) == (0, 0)
    assert moved_stats["context_policy"] == "source_imports_and_active_context_excluding_target"
    assert group_stats["context_policy"] == "source_imports_and_active_context_excluding_target"
    # The incomplete context is rejected by Lean, so the extractor must
    # record a failure with Lean's own diagnostic instead of a bare status.
    for failures in (moved_stats["failures"], group_stats["failures"]):
        assert failures
        assert set(item["reason"] for item in failures) <= \
            {"goal inspection failed", "tactic replay did not close goal"}
        assert failures[0]["detail"]


@pytest.mark.lean
def test_namespaced_declarations_get_unique_ids(mathlib_root):
    rows, stats = extract_mathlib_file(LeanClient(), mathlib_root,
                                       "Mathlib/Algebra/BigOperators/ModEq.lean", 5,
                                       "listSum_map")
    assert {row["source_declaration"] for row in rows} == \
        {"Nat.ModEq.listSum_map", "Int.ModEq.listSum_map"}
    assert len({row["theorem_id"] for row in rows}) == 2
    assert len({row["theorem"].split()[1] for row in rows}) == 2


# --- the failures the extractor keeps --------------------------------------

def test_an_unsupported_tactic_block_is_recorded_as_a_failure(tmp_path):
    # A block that the narrow parser cannot replay has to be visible in the
    # statistics, not silently dropped from the count.
    source = tmp_path / "Mathlib" / "A.lean"
    source.parent.mkdir(parents=True)
    source.write_text("theorem t : True := by\n  · trivial\n")
    rows, stats = extract_mathlib_file(LeanClient(), tmp_path, "Mathlib/A.lean", limit=5)
    assert rows == []
    assert stats["failures"]
    assert stats["failures"][0]["reason"] == "unsupported tactic block"
    assert stats["verified_examples"] == 0


def test_a_multi_tactic_proof_is_recorded_as_a_failure(tmp_path):
    source = tmp_path / "Mathlib" / "A.lean"
    source.parent.mkdir(parents=True)
    source.write_text("theorem t : True := by\n  trivial\n  trivial\n")
    rows, stats = extract_mathlib_file(LeanClient(), tmp_path, "Mathlib/A.lean", limit=5)
    assert rows == []
    assert stats["failures"][0]["reason"] == "multi-tactic proof not supported by this pilot"


def test_a_missing_tactic_body_is_recorded_as_a_failure(tmp_path):
    source = tmp_path / "Mathlib" / "A.lean"
    source.parent.mkdir(parents=True)
    source.write_text("theorem t : True := by\n")
    rows, stats = extract_mathlib_file(LeanClient(), tmp_path, "Mathlib/A.lean", limit=5)
    assert rows == []
    assert stats["failures"][0]["reason"] == "missing tactic body"


def test_the_statistics_count_the_headers_that_were_seen(tmp_path):
    source = tmp_path / "Mathlib" / "A.lean"
    source.parent.mkdir(parents=True)
    source.write_text("theorem t : True := by\n  · trivial\n")
    _, stats = extract_mathlib_file(LeanClient(), tmp_path, "Mathlib/A.lean", limit=5)
    assert stats["declaration_headers_seen"] == 1
    assert stats["recognized_simple_headers"] == 1
    assert stats["unrecognized_declaration_headers"] == 0
