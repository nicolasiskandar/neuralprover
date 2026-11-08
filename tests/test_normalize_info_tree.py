"""The InfoTree normalizer: which nodes become examples, and which do not.

The normalizer runs on raw trace data, so its exclusion counters are the only
record of what was dropped.  These cases check both: the examples it keeps
and the reasons it gives for the ones it does not.
"""
import json

import pytest

from neuralproof.data.normalize_info_tree import (_int, _kind_matches_source, _line_at,
                                                  _source_tactic, normalize_trace,
                                                  normalize_trace_file)

SOURCE = "import Lean\ntheorem t : True := by\n  trivial\n"
TRIVIAL_START = SOURCE.index("trivial")
TRIVIAL_END = TRIVIAL_START + len("trivial")


@pytest.fixture
def source_file(tmp_path):
    path = tmp_path / "Mathlib" / "A.lean"
    path.parent.mkdir(parents=True)
    path.write_text(SOURCE)
    return path


def proof_node(**overrides):
    node = {"syntax_kind": "Lean.Parser.Term.byTactic", "declaration": "t",
            "source_start": "0", "source_end": str(len(SOURCE.encode()))}
    node.update(overrides)
    return node


def tactic_node(**overrides):
    node = {"syntax_kind": "Lean.Parser.Tactic.tacticTrivial", "declaration": "t",
            "source_start": str(TRIVIAL_START), "source_end": str(TRIVIAL_END),
            "goal_state": "⊢ True", "result_state": "no goals", "completed": True}
    node.update(overrides)
    return node


# --- the small helpers ------------------------------------------------------

def test_an_offset_is_read_as_a_number():
    assert _int("12") == 12
    assert _int(12) == 12
    assert _int(None) is None
    assert _int("not a number") is None


def test_a_line_is_counted_in_bytes_not_in_code_points():
    # Lean String.Pos.Raw offsets count UTF-8 bytes; a non-ASCII character
    # before the offset would shift a code-point count.
    raw = "α\nβ\n".encode("utf-8")
    assert _line_at(raw, 0) == 0
    assert _line_at(raw, len("α".encode("utf-8"))) == 0
    assert _line_at(raw, len("α\n".encode("utf-8"))) == 1


def test_the_source_text_of_a_span_is_read_and_stripped():
    raw = SOURCE.encode("utf-8")
    assert _source_tactic(raw, TRIVIAL_START, TRIVIAL_END) == "trivial"
    assert _source_tactic(raw, 0, 0) == ""


def test_the_syntax_kind_is_matched_against_the_source_text():
    assert _kind_matches_source("Lean.Parser.Tactic.tacticTrivial", "trivial")
    assert _kind_matches_source("Lean.Parser.Tactic.rewriteSeq", "rw [h]")
    assert _kind_matches_source("Lean.Parser.Tactic.simpAll", "simp_all")
    assert not _kind_matches_source("Lean.Parser.Tactic.tacticTrivial", "rfl")
    assert not _kind_matches_source("Lean.Parser.Tactic.tacticTrivial", "1")


# --- the normalizer ---------------------------------------------------------

def test_a_source_backed_tactic_becomes_an_example(source_file):
    trace = {"source_file": "Mathlib/A.lean", "source_revision": "pinned",
             "traces": [proof_node(), tactic_node()]}
    rows, stats = normalize_trace(trace, source_file)
    assert len(rows) == 1
    row = rows[0]
    assert row["target_tactic"] == "trivial"
    assert row["goal_state"] == "⊢ True"
    assert row["result_state"] == "no goals"
    assert row["source_declaration"] == "t"
    assert row["source_line"] == 3
    assert row["source_start"] == TRIVIAL_START
    assert row["validation"] == "original_file_elaborated; transition_replay_pending"
    assert stats["output_examples"] == 1
    assert stats["input_nodes"] == 2


def test_the_example_id_is_stable_and_names_its_source(source_file):
    trace = {"source_file": "Mathlib/A.lean", "traces": [proof_node(), tactic_node()]}
    first, _ = normalize_trace(trace, source_file)
    second, _ = normalize_trace(trace, source_file)
    assert first[0]["example_id"] == second[0]["example_id"]
    assert "A_lean" in first[0]["example_id"]


def test_the_context_of_an_example_is_the_source_context(source_file):
    trace = {"source_file": "Mathlib/A.lean", "traces": [proof_node(), tactic_node()]}
    rows, _ = normalize_trace(trace, source_file)
    assert "import Lean" in rows[0]["context"]


def test_a_wrapper_node_is_not_an_example(source_file):
    trace = {"source_file": "Mathlib/A.lean", "traces": [
        proof_node(), tactic_node(syntax_kind="Lean.Parser.Tactic.tacticSeq")]}
    rows, stats = normalize_trace(trace, source_file)
    assert rows == []
    # The wrapper and the `by` of the declaration header are both counted:
    # neither is a tactic a model could be asked to produce.
    assert stats["excluded"]["wrapper_or_non_tactic"] == 2


def test_a_node_without_a_span_is_counted(source_file):
    trace = {"source_file": "Mathlib/A.lean", "traces": [
        proof_node(), {"syntax_kind": "Lean.Parser.Tactic.tacticTrivial", "declaration": "t"}]}
    rows, stats = normalize_trace(trace, source_file)
    assert rows == []
    assert stats["excluded"]["missing_span"] == 1


def test_a_node_with_an_out_of_range_span_is_counted(source_file):
    trace = {"source_file": "Mathlib/A.lean", "traces": [
        proof_node(), tactic_node(source_start="0", source_end="99999")]}
    rows, stats = normalize_trace(trace, source_file)
    assert rows == []
    assert stats["excluded"]["invalid_range"] == 1


def test_a_node_with_an_empty_source_range_is_counted(source_file):
    trace = {"source_file": "Mathlib/A.lean", "traces": [
        proof_node(), tactic_node(source_start=str(TRIVIAL_START), source_end=str(TRIVIAL_START))]}
    rows, stats = normalize_trace(trace, source_file)
    assert rows == []
    assert stats["excluded"]["empty_source"] == 1


def test_a_declaration_less_node_outside_a_proof_is_counted(source_file):
    trace = {"source_file": "Mathlib/A.lean", "traces": [
        proof_node(source_start="12", source_end="34"),
        tactic_node(declaration="")]}
    rows, stats = normalize_trace(trace, source_file)
    assert rows == []
    assert stats["excluded"]["outside_proof"] == 1


def test_a_declaration_less_node_inside_two_proofs_is_counted(source_file):
    trace = {"source_file": "Mathlib/A.lean", "traces": [
        proof_node(declaration="t"), proof_node(declaration="u"),
        tactic_node(declaration="")]}
    rows, stats = normalize_trace(trace, source_file)
    assert rows == []
    assert stats["excluded"]["ambiguous_owner"] == 1


def test_two_nodes_on_the_same_span_are_deduplicated(source_file):
    # The InfoTree reports the same span twice under different kinds; the
    # one whose kind matches the source text is the one that is kept.
    trace = {"source_file": "Mathlib/A.lean", "traces": [
        proof_node(), tactic_node(), tactic_node(syntax_kind="Lean.Parser.Tactic.tacticRfl")]}
    rows, stats = normalize_trace(trace, source_file)
    assert len(rows) == 1
    assert stats["deduplicated_nodes"] == 1
    assert rows[0]["syntax_kind"] == "Lean.Parser.Tactic.tacticTrivial"


def test_a_multiline_tactic_is_excluded(tmp_path):
    # A source span that crosses a line may bundle more than one command, so
    # the normalizer does not treat it as a single next-tactic target.
    text = "import Lean\ntheorem t : True := by\n  exact\n    True.intro\n"
    path = tmp_path / "Mathlib" / "M.lean"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    tactic_start = len(text[:text.index("exact")].encode())
    tactic_end = len(text[:text.index("True.intro") + len("True.intro")].encode())
    proof_start = len(text[:text.index("by")].encode())
    trace = {"source_file": "Mathlib/M.lean", "traces": [
        {"declaration": "t", "syntax_kind": "Lean.Parser.Term.byTactic",
         "source_start": str(proof_start), "source_end": str(len(text.encode()))},
        {"declaration": "t", "syntax_kind": "Lean.Parser.Tactic.tacticExact",
         "source_start": str(tactic_start), "source_end": str(tactic_end),
         "goal_state": "⊢ True", "result_state": "no goals", "completed": True},
    ]}
    rows, stats = normalize_trace(trace, path)
    assert rows == []
    # The `by` header and the multiline tactic are both non-targets.
    assert stats["excluded"]["wrapper_or_non_tactic"] == 2



def test_the_split_of_an_example_follows_its_file(source_file):
    from neuralproof.data.splits import split_for
    trace = {"source_file": "Mathlib/A.lean", "traces": [proof_node(), tactic_node()]}
    rows, _ = normalize_trace(trace, source_file, seed="neuralproof-v1")
    assert rows[0]["split"] == split_for("Mathlib/A.lean", "neuralproof-v1")


def test_the_statistics_name_the_policies_in_force(source_file):
    trace = {"source_file": "Mathlib/A.lean", "traces": [proof_node(), tactic_node()]}
    _, stats = normalize_trace(trace, source_file)
    assert stats["context_policy"] == "source_imports_and_active_context_excluding_target"
    assert "not claimed" in stats["validation_policy"]


def test_the_file_writer_writes_the_rows_and_the_statistics(source_file, tmp_path):
    trace = {"source_file": "Mathlib/A.lean", "traces": [proof_node(), tactic_node()]}
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(trace))
    output = tmp_path / "normalized.jsonl"
    stats = normalize_trace_file(trace_path, source_file, output)
    rows = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert stats["output_examples"] == 1
    assert (tmp_path / "normalized.jsonl.stats.json").exists()
