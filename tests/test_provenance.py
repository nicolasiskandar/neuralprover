"""Provenance: the digests and states that describe how an artifact was made."""
import json
import os
import subprocess
import sys

import pytest

from neuralproof.data.provenance import (code_diff_sha256, code_revision, current_command,
                                         sha256_file, sha256_text, working_tree_state,
                                         write_manifest)


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """An empty git repository the test can change while it runs."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    git("config", "commit.gpgsign", "false")
    monkeypatch.chdir(repo)
    return repo


def test_file_digest_matches_the_content(tmp_path):
    path = tmp_path / "x.txt"
    path.write_text("abc")
    assert sha256_file(path) == sha256_text("abc")


def test_a_missing_file_has_no_digest(tmp_path):
    assert sha256_file(tmp_path / "missing.txt") is None


def test_a_directory_has_no_digest(tmp_path):
    assert sha256_file(tmp_path) is None


def test_the_code_revision_is_a_commit_id_or_nothing():
    revision = code_revision()
    assert revision is None or (len(revision) == 40 and all(c in "0123456789abcdef" for c in revision))


def test_the_working_tree_state_is_reported():
    assert working_tree_state() in {"clean", "dirty", "unknown"}


def test_the_working_tree_state_notices_an_uncommitted_change(git_repo):
    (git_repo / "tracked.py").write_text("x = 1\n")
    assert working_tree_state() == "dirty"


def test_manifest_records_the_command_and_the_inputs(tmp_path):
    path = write_manifest(tmp_path / "nested" / "manifest.json", {"artifact": "x"})
    assert json.loads(path.read_text())["artifact"] == "x"


def test_the_manifest_is_valid_json_with_a_trailing_newline(tmp_path):
    path = write_manifest(tmp_path / "manifest.json", {"artifact": "x"})
    text = path.read_text()
    assert text.endswith("\n")
    assert json.loads(text) == {"artifact": "x"}


def test_the_code_digest_covers_untracked_files(git_repo):
    # `git diff` does not mention an untracked file, but a new module
    # that an artifact depends on is part of the code that produced it.
    (git_repo / "tracked.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "tracked.py"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=git_repo, check=True, capture_output=True)
    committed = code_diff_sha256()
    (git_repo / "new_module.py").write_text("y = 2\n")
    with_new_file = code_diff_sha256()
    (git_repo / "new_module.py").write_text("y = 3\n")
    with_changed_file = code_diff_sha256()
    assert committed is not None
    assert committed != with_new_file
    assert with_new_file != with_changed_file


def test_a_staged_change_is_part_of_the_digest(git_repo):
    # `git diff HEAD` covers the index as well as the working tree, so a
    # staged change has to move the digest.
    (git_repo / "tracked.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "tracked.py"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=git_repo, check=True, capture_output=True)
    committed = code_diff_sha256()
    (git_repo / "tracked.py").write_text("x = 2\n")
    subprocess.run(["git", "add", "tracked.py"], cwd=git_repo, check=True, capture_output=True)
    assert code_diff_sha256() != committed


def test_a_tree_outside_a_repository_has_no_digest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inside = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=tmp_path,
                            capture_output=True)
    if inside.returncode == 0:
        pytest.skip("the temporary directory is inside a git repository")
    assert code_diff_sha256() is None


def test_the_current_command_names_the_module_entry_point(monkeypatch):
    monkeypatch.setattr(
        sys, "orig_argv",
        ["/usr/bin/python", "-m", "neuralproof.cli", "doctor"], raising=False)
    assert current_command() == "python -m neuralproof.cli doctor"


def test_the_current_command_names_a_script_entry_point(monkeypatch):
    monkeypatch.setattr(
        sys, "orig_argv",
        ["/usr/bin/python", "scripts/build_benchmark_theorems.py", "--count", "5"],
        raising=False)
    assert current_command() == "python scripts/build_benchmark_theorems.py --count 5"
