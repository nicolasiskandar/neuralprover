"""The staged InfoTree corpus: checkpoints, resumes, and visible failures."""
import json

import pytest

from neuralproof.data.info_tree_corpus import extract_info_tree_corpus


@pytest.fixture
def traced_root(tmp_path):
    root = tmp_path / "mathlib"
    source = root / "Mathlib" / "A.lean"
    source.parent.mkdir(parents=True)
    text = "import Lean\ntheorem t : True := by\n  trivial\n"
    source.write_text(text)
    start = len(text[:text.index("trivial")].encode())
    end = start + len("trivial")
    trace = {"source_file": "Mathlib/A.lean", "source_revision": "pinned", "traces": [
        {"declaration": "t", "syntax_kind": "Lean.Parser.Term.byTactic",
         "source_start": str(start - 4), "source_end": str(end + 1),
         "tactic": "by", "goal_state": "⊢ True", "result_state": "no goals", "completed": True},
        {"declaration": "t", "syntax_kind": "Lean.Parser.Tactic.tacticTrivial",
         "source_start": str(start), "source_end": str(end),
         "tactic": "trivial", "goal_state": "⊢ True", "result_state": "no goals", "completed": True},
    ]}
    return root, trace


def test_checkpoint_and_resume(monkeypatch, tmp_path, traced_root):
    root, trace = traced_root
    output = tmp_path / "out"
    calls = []

    def fake_trace(*args, **kwargs):
        calls.append(args)
        return trace

    monkeypatch.setattr("neuralproof.data.info_tree_corpus.trace_file", fake_trace)
    first = extract_info_tree_corpus(root, output, files=1)
    second = extract_info_tree_corpus(root, output, files=1)
    assert len(calls) == 1
    assert first["examples"] == 1
    assert second["duplicate_example_ids"] == 0
    assert second["cross_split_declaration_name_overlap_pairs"] == 0
    assert second["split_source_files"]["train"] == 1
    row = json.loads((output / "examples.jsonl").read_text())
    assert row["target_tactic"] == "trivial"
    assert row["validation"] == "original_file_elaborated; transition_replay_pending"


def test_a_failing_file_is_recorded_and_the_tranche_continues(monkeypatch, tmp_path, traced_root):
    # One module that cannot be traced must not lose the work on the others,
    # and the failure has to stay visible in the summary.
    root, trace = traced_root
    (root / "Mathlib" / "B.lean").write_text("import Lean\ntheorem u : True := by\n  trivial\n")
    output = tmp_path / "out"

    def fake_trace(source, **kwargs):
        if str(source).endswith("B.lean"):
            raise RuntimeError("Lean could not elaborate the module")
        return trace

    monkeypatch.setattr("neuralproof.data.info_tree_corpus.trace_file", fake_trace)
    summary = extract_info_tree_corpus(root, output, files=2)
    assert summary["file_status"]["error"] == 1
    assert summary["file_status"]["ok"] == 1
    assert summary["failed_files"][0]["source_file"] == "Mathlib/B.lean"
    assert "Lean could not elaborate" in summary["failed_files"][0]["error"]


def test_the_file_count_has_to_be_positive(tmp_path, traced_root):
    root, _ = traced_root
    with pytest.raises(ValueError):
        extract_info_tree_corpus(root, tmp_path / "out", files=0)


def test_the_per_file_cap_cannot_be_negative(tmp_path, traced_root):
    root, _ = traced_root
    with pytest.raises(ValueError):
        extract_info_tree_corpus(root, tmp_path / "out", files=1, per_file=-1)


def test_the_timeout_has_to_be_positive(tmp_path, traced_root):
    root, _ = traced_root
    with pytest.raises(ValueError):
        extract_info_tree_corpus(root, tmp_path / "out", files=1, timeout=0)


def test_resume_rejects_a_changed_manifest(monkeypatch, tmp_path, traced_root):
    root, trace = traced_root
    output = tmp_path / "out"
    monkeypatch.setattr("neuralproof.data.info_tree_corpus.trace_file", lambda *a, **k: trace)
    extract_info_tree_corpus(root, output, files=1, timeout=300)
    with pytest.raises(ValueError, match="timeout_seconds"):
        extract_info_tree_corpus(root, output, files=1, timeout=600)


def test_resume_survives_missing_checkpoint_files(monkeypatch, tmp_path, traced_root):
    # If the checkpoint says the tranche is complete but the JSONL files were
    # removed, the summary pass must report zero examples instead of crashing.
    root, trace = traced_root
    output = tmp_path / "out"
    monkeypatch.setattr("neuralproof.data.info_tree_corpus.trace_file", lambda *a, **k: trace)
    extract_info_tree_corpus(root, output, files=1)
    (output / "examples.jsonl").unlink()
    (output / "file_stats.jsonl").unlink()
    summary = extract_info_tree_corpus(root, output, files=1)
    assert summary["examples"] == 0


def test_a_broad_import_is_an_exact_line_not_a_narrower_module():
    from neuralproof.data.info_tree_corpus import _is_broad_import_context
    assert _is_broad_import_context("import Lean\nimport Mathlib")
    assert _is_broad_import_context("public import Mathlib")
    assert not _is_broad_import_context("import Mathlib.Tactic")
    assert not _is_broad_import_context("import Lean")

