"""Invariants the generated corpora have to keep.

These cases read the artifacts that are actually on disk.  They are the
cheapest possible guard against the two failures that cost this project a
result before: a label that is not a tactic, and a file that leaks from the
test split into the training split.
"""
import json
from pathlib import Path

import pytest

from neuralproof.data.preprocessing import is_tactic_target
from neuralproof.data.provenance import sha256_file
from neuralproof.models.prompt import format_tactic_prompt

pytestmark = pytest.mark.corpus

REPO_ROOT = Path(__file__).parents[1]

PROCESSED = [
    ("sample", "data/processed"),
    ("mathlib-200", "data/mathlib-200/processed"),
    ("nat-basic", "data/validated/nat-basic-processed"),
    ("info-tree-200", "data/mathlib-info-tree-200/processed"),
]


def load_rows(directory: Path, split: str):
    path = directory / f"{split}.jsonl"
    if not path.exists():
        return None
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture(params=PROCESSED, ids=[name for name, _ in PROCESSED])
def processed(request):
    """Every processed dataset that is present in this checkout."""
    name, relative = request.param
    directory = REPO_ROOT / relative
    if not directory.exists():
        pytest.skip(f"{relative} is not present in this checkout")
    return name, directory


def test_the_processed_rows_carry_a_tactic_target(processed):
    # A row whose target is the `by` of a header, the `where` of a structure
    # instance or a parser placeholder teaches the model to answer with a
    # keyword that closes no goal.
    _, directory = processed
    for split in ("train", "validation", "test"):
        rows = load_rows(directory, split)
        if rows is None:
            continue
        for row in rows:
            assert is_tactic_target(row["target_tactic"]), row["target_tactic"]


def test_the_prompt_of_a_row_is_the_canonical_prompt(processed):
    # The training prompt and the prompt the evaluator builds have to be
    # the same bytes, or the model is trained on a format it is never asked
    # for.  This was the difference between a broken and a working harness.
    _, directory = processed
    for split in ("train", "validation", "test"):
        rows = load_rows(directory, split)
        if rows is None:
            continue
        for row in rows:
            assert row["prompt"] == format_tactic_prompt(row["context"], row["goal_state"])


def test_no_source_file_is_in_two_splits(processed):
    # A file that appears in both the training and the test split leaks the
    # test set into training.
    _, directory = processed
    seen = {}
    for split in ("train", "validation", "test"):
        rows = load_rows(directory, split)
        if rows is None:
            continue
        for row in rows:
            source = row.get("source_file", "")
            assert seen.setdefault(source, split) == split, source


def test_the_manifest_matches_the_files_it_describes(processed):
    name, directory = processed
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("the dataset has no manifest")
    manifest = json.loads(manifest_path.read_text())
    for split, description in manifest.get("outputs", {}).items():
        path = REPO_ROOT / description["path"]
        if not path.exists():
            path = directory / f"{split}.jsonl"
        assert path.exists(), description["path"]
        assert sha256_file(path) == description["sha256"], split
        assert len(load_rows(directory, split)) == description["rows"]


def test_the_manifest_records_the_policies_that_shaped_the_data(processed):
    manifest_path = processed[1] / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("the dataset has no manifest")
    manifest = json.loads(manifest_path.read_text())
    assert manifest["split_counts"] == {name: description["rows"]
                                        for name, description in manifest["outputs"].items()}
    assert "label_policy" in manifest
    assert "goal_scope_policy" in manifest
    assert "code_diff_sha256" in manifest


def test_the_manifest_says_what_its_own_digest_does_not_cover(processed):
    # The digest is taken before the manifest is written, and the manifest
    # is a tracked file, so the digest identifies the code and the inputs
    # and not the tree that includes the manifest itself.  The artifact has
    # to say so rather than let the digest look absolute.
    manifest_path = processed[1] / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("the dataset has no manifest")
    manifest = json.loads(manifest_path.read_text())
    assert any("code_diff_sha256" in caveat for caveat in manifest["caveats"])


def test_every_row_carries_a_known_scope(processed):
    _, directory = processed
    for split in ("train", "validation", "test"):
        rows = load_rows(directory, split)
        if rows is None:
            continue
        for row in rows:
            assert row.get("goal_scope") in {"proof", "focus", "conv"}


def test_the_trainer_selects_exactly_the_proof_scoped_rows():
    # The trainer is told to use the proof-scope rows only; the processed
    # file keeps the other scopes visible so the drop is auditable.
    from neuralproof.models.finetune import select_training_rows

    directory = REPO_ROOT / "data/mathlib-info-tree-200/processed"
    if not directory.exists():
        pytest.skip("the 200-file corpus is not present in this checkout")
    rows = load_rows(directory, "train")
    if rows is None:
        pytest.skip("the 200-file corpus has no training split")
    kept, dropped = select_training_rows(rows, "proof")
    assert kept
    assert dropped == len(rows) - len(kept)
    assert all(row.get("goal_scope") == "proof" for row in kept)
