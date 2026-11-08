"""The replay corpus: rows that Lean confirmed, and rows that it could not."""
import json

import pytest

from neuralproof.data.replay_corpus import replay_corpus


@pytest.fixture
def source_rows(tmp_path):
    """A small corpus that the replay has to confirm."""
    path = tmp_path / "examples.jsonl"
    rows = [{"example_id": "e1", "source_file": "Mathlib/A.lean", "source_declaration": "A.t",
             "goal_state": "⊢ True", "target_tactic": "trivial", "split": "train"},
            {"example_id": "e2", "source_file": "Mathlib/A.lean", "source_declaration": "A.u",
             "goal_state": "⊢ False", "target_tactic": "rfl", "split": "train"}]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


@pytest.fixture
def traced(monkeypatch):
    """Stand in for the Lean trace and the two normalisation passes."""
    def install(available):
        monkeypatch.setattr("neuralproof.data.replay_corpus.trace_file",
                            lambda *args, **kwargs: {"traces": []})
        monkeypatch.setattr("neuralproof.data.replay_corpus.normalize_trace",
                            lambda *args, **kwargs: (list(available), {}))
        monkeypatch.setattr("neuralproof.data.replay_corpus.validate_trace_examples",
                            lambda *args, **kwargs: (list(available), {"validation_counts": {}}))

    return install


def test_a_replayed_row_is_written_as_replayed(tmp_path, source_rows, traced):
    traced([{"example_id": "e1", "source_file": "Mathlib/A.lean", "source_declaration": "A.t",
             "goal_state": "⊢ True", "target_tactic": "trivial", "validation": "replayed"}])
    output = tmp_path / "out"
    summary = replay_corpus(source_rows, tmp_path, output)
    rows = [json.loads(line) for line in (output / "examples.jsonl").read_text().splitlines()
            if line.strip()]
    assert len(rows) == 2
    assert summary["replay_rows"] == 1
    assert summary["failed_rows"] == 1


def test_a_row_that_the_trace_does_not_contain_is_marked_failed(tmp_path, source_rows, traced):
    traced([])
    output = tmp_path / "out"
    summary = replay_corpus(source_rows, tmp_path, output)
    rows = [json.loads(line) for line in (output / "examples.jsonl").read_text().splitlines()
            if line.strip()]
    assert all(row["validation"] == "failed" for row in rows)
    assert "example_id_missing_from_current_trace" in rows[0]["validation_reason"]
    assert summary["failed_rows"] == 2
    assert summary["file_status"]["partial"] == 1


def test_a_failing_file_is_recorded_and_the_tranche_continues(tmp_path, source_rows,
                                                               monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("Lean could not elaborate the module")

    monkeypatch.setattr("neuralproof.data.replay_corpus.trace_file", explode)
    output = tmp_path / "out"
    summary = replay_corpus(source_rows, tmp_path, output)
    assert summary["file_status"]["error"] == 1
    assert summary["failed_rows"] == 2
    rows = [json.loads(line) for line in (output / "examples.jsonl").read_text().splitlines()
            if line.strip()]
    assert "RuntimeError" in rows[0]["validation_reason"]


def test_the_file_count_cannot_be_negative(tmp_path, source_rows, traced):
    traced([])
    with pytest.raises(ValueError):
        replay_corpus(source_rows, tmp_path, tmp_path / "out", files=-1)


def test_the_timeout_has_to_be_positive(tmp_path, source_rows, traced):
    traced([])
    with pytest.raises(ValueError):
        replay_corpus(source_rows, tmp_path, tmp_path / "out", timeout=0)


def test_resume_rejects_a_changed_manifest(tmp_path, source_rows, traced):
    traced([])
    output = tmp_path / "out"
    replay_corpus(source_rows, tmp_path, output, timeout=300)
    with pytest.raises(ValueError, match="timeout_seconds"):
        replay_corpus(source_rows, tmp_path, output, timeout=600)


def test_the_manifest_pins_the_input_digest(tmp_path, source_rows, traced):
    traced([])
    output = tmp_path / "out"
    replay_corpus(source_rows, tmp_path, output)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["input_sha256"]
    assert manifest["selected_files"] == 1
    assert manifest["schema_version"] == 1


def test_file_stats_are_written_for_the_processed_tranche(tmp_path, source_rows, traced):
    traced([{"example_id": "e1", "source_file": "Mathlib/A.lean",
             "source_declaration": "A.t", "goal_state": "⊢ True",
             "target_tactic": "trivial", "validation": "replayed"}])
    output = tmp_path / "out"
    replay_corpus(source_rows, tmp_path, output)
    stats = [json.loads(line) for line in
             (output / "file_stats.jsonl").read_text().splitlines() if line.strip()]
    assert [row["source_file"] for row in stats] == ["Mathlib/A.lean"]
    assert stats[0]["status"] in {"ok", "partial", "error"}
