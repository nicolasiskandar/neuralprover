"""Shared fixtures for the neuralproof test suite.

The suite talks to three external things: the pinned Lean toolchain, a
Mathlib checkout, and a local Hugging Face model cache.  Each is exposed
here so a test can ask for it by name instead of hard-coding a path, and so
a missing dependency turns into a clear skip instead of a confusing error.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repository root, used to locate the pinned Lean project."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def lean_project() -> Path:
    """The pinned Lean 4 project that the client shells out to."""
    project = REPO_ROOT / "lean"
    if not project.exists():
        pytest.skip("the pinned Lean project is not checked out")
    return project


@pytest.fixture(scope="session")
def mathlib_root() -> Path:
    """The pinned Mathlib checkout used by the extraction tests."""
    root = REPO_ROOT / "lean" / ".lake" / "packages" / "mathlib"
    if not root.exists():
        pytest.skip("the pinned Mathlib checkout is not available")
    return root


@pytest.fixture(scope="session")
def lean_client():
    """A Lean client with a short timeout, shared by the whole session."""
    from neuralproof.lean.client import LeanClient

    return LeanClient(timeout=20)


@pytest.fixture(autouse=True)
def offline_models(monkeypatch):
    """Keep the test suite off the network.

    A test that reaches Hugging Face silently makes the suite depend on a
    network round trip and turns a cache miss into a hang.  The model cache
    is local, so the suite runs offline and reports a missing model as an
    error instead of waiting for a download.
    """
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    cache = Path.home() / ".cache" / "huggingface"
    if cache.exists():
        monkeypatch.setenv("HF_HOME", str(cache))


@pytest.fixture
def write_jsonl(tmp_path):
    """Write rows to a JSONL file and return its path.

    The evaluation and the trainer both read newline-delimited JSON, so the
    fixture writes exactly that and nothing else.
    """
    def _write(rows, name: str = "rows.jsonl") -> Path:
        path = tmp_path / name
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        return path

    return _write


@pytest.fixture
def tactic_row():
    """A minimal mined tactic row, overridable per test."""
    def _row(**overrides):
        row = {"example_id": "row-1", "split": "test", "source_file": "Mathlib/A.lean",
               "source_declaration": "A.decl", "context": "import Lean",
               "goal_state": "⊢ True", "target_tactic": "trivial"}
        row.update(overrides)
        return row

    return _row


@pytest.fixture
def fake_predictor():
    """Build a predictor that returns a fixed list of tactics.

    The search and evaluation code only rely on `predict(state, k)`, so a
    stand-in keeps those tests independent of the model stack.
    """
    from neuralproof.lean.client import TacticCandidate

    def _build(tactics, score: float = 1.0):
        class _Fake:
            def __init__(self):
                self.calls = []

            def predict(self, state, k):
                self.calls.append((state, k))
                return [TacticCandidate(tactic, score - index * 0.01)
                        for index, tactic in enumerate(tactics[:k])]

        return _Fake()

    return _build
