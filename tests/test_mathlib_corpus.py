"""The resumable Mathlib corpus: checkpoints, resumes, and visible failures."""
import json

import pytest

from neuralproof.data.corpus import extract_corpus


@pytest.fixture
def mathlib_root(tmp_path):
    root = tmp_path / "mathlib"
    (root / "Mathlib" / "A").mkdir(parents=True)
    (root / "Mathlib" / "A" / "One.lean").write_text("-- one")
    (root / "Mathlib" / "A" / "Two.lean").write_text("-- two")
    return root


def test_checkpoint_resume_and_file_split(monkeypatch, tmp_path, mathlib_root):
    output = tmp_path / "out"
    row = {"source_file": "Mathlib/A/One.lean", "source_declaration": "A.one",
           "goal_state": "⊢ True", "target_tactic": "trivial", "context": "import A",
           "split": "wrong"}

    calls = []

    def extract(_client, _root, relative, limit):
        calls.append(relative)
        return ([dict(row)] if relative.endswith("One.lean") else [],
                {"source_file": relative, "failures": []})

    monkeypatch.setattr("neuralproof.data.corpus.LeanClient", lambda *a, **k: object())
    monkeypatch.setattr("neuralproof.data.corpus.extract_mathlib_file", extract)
    first = extract_corpus(mathlib_root, output, files=2, per_file=1)
    second = extract_corpus(mathlib_root, output, files=2, per_file=1)
    with pytest.raises(ValueError, match="per_file_example_cap"):
        extract_corpus(mathlib_root, output, files=2, per_file=2)

    assert calls == ["Mathlib/A/One.lean", "Mathlib/A/Two.lean"]
    assert first["examples"] == 1
    assert second["examples"] == 1
    assert second["duplicate_source_declaration_ids"] == 0
    assert second["broad_import_context_rows"] == 0
    saved = json.loads((output / "examples.jsonl").read_text())
    assert saved["split"] in {"train", "validation", "test"}
    assert len((output / "file_stats.jsonl").read_text().splitlines()) == 2


def test_resume_rejects_changed_file_manifest(monkeypatch, tmp_path, mathlib_root):
    output = tmp_path / "out"
    monkeypatch.setattr("neuralproof.data.corpus.LeanClient", lambda *a, **k: object())
    monkeypatch.setattr("neuralproof.data.corpus.extract_mathlib_file",
                        lambda *a, **k: ([], {"failures": []}))
    extract_corpus(mathlib_root, output, files=1, per_file=1)
    (mathlib_root / "Mathlib" / "A" / "Two.lean").write_text("-- two")
    with pytest.raises(ValueError, match="file_list_sha256"):
        extract_corpus(mathlib_root, output, files=2, per_file=1)


def test_the_file_count_has_to_be_positive(monkeypatch, tmp_path, mathlib_root):
    monkeypatch.setattr("neuralproof.data.corpus.LeanClient", lambda *a, **k: object())
    with pytest.raises(ValueError):
        extract_corpus(mathlib_root, tmp_path / "out", files=0, per_file=1)


def test_the_per_file_cap_has_to_be_positive(monkeypatch, tmp_path, mathlib_root):
    monkeypatch.setattr("neuralproof.data.corpus.LeanClient", lambda *a, **k: object())
    with pytest.raises(ValueError):
        extract_corpus(mathlib_root, tmp_path / "out", files=1, per_file=0)


def test_a_missing_mathlib_checkout_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr("neuralproof.data.corpus.LeanClient", lambda *a, **k: object())
    with pytest.raises(FileNotFoundError):
        extract_corpus(tmp_path / "nowhere", tmp_path / "out", files=1, per_file=1)


def test_the_manifest_records_the_selection(monkeypatch, tmp_path, mathlib_root):
    output = tmp_path / "out"
    monkeypatch.setattr("neuralproof.data.corpus.LeanClient", lambda *a, **k: object())
    monkeypatch.setattr("neuralproof.data.corpus.extract_mathlib_file",
                        lambda *a, **k: ([], {"failures": []}))
    summary = extract_corpus(mathlib_root, output, files=1, per_file=1)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["selected_files"] == 1
    assert manifest["file_list_sha256"]
    assert summary["completed_files"] == 1
