"""Tests for scripts/check_benchmark.py verification tool."""
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_checker():
    path = REPO_ROOT / "scripts" / "check_benchmark.py"
    spec = importlib.util.spec_from_file_location("check_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def test_cli_subcommands_check():
    ok, msg = checker.check_cli_subcommands()
    assert ok is True
    assert "replay-corpus" in msg


def test_metrics_estimator_check():
    ok, msg = checker.check_metrics_estimator()
    assert ok is True


def test_check_benchmark_file_valid(tmp_path):
    bench = tmp_path / "bench.jsonl"
    rows = [
        {
            "theorem_id": "t1",
            "theorem": "theorem t1 : True",
            "context": "import Lean",
            "source_file": "A.lean",
            "source_declaration": "t1",
            "split": "test",
            "completed_after_first_tactic": True,
        },
        {
            "theorem_id": "t2",
            "theorem": "theorem t2 : False",
            "context": "import Lean",
            "source_file": "B.lean",
            "source_declaration": "t2",
            "split": "test",
            "completed_after_first_tactic": False,
        },
    ]
    bench.write_text("".join(json.dumps(r) + "\n" for r in rows))
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")

    ok, msg, stats = checker.check_benchmark_file(bench, manifest)
    assert ok is True
    assert stats["theorems"] == 2
    assert stats["single_step"] == 1
    assert stats["multi_step"] == 1
    assert stats["unique_files"] == 2


def test_check_benchmark_file_fails_on_wrong_split(tmp_path):
    bench = tmp_path / "bench.jsonl"
    row = {
        "theorem_id": "t1",
        "theorem": "theorem t1 : True",
        "context": "import Lean",
        "source_file": "A.lean",
        "source_declaration": "t1",
        "split": "train",
    }
    bench.write_text(json.dumps(row) + "\n")
    ok, msg, _ = checker.check_benchmark_file(bench)
    assert ok is False
    assert "expected 'test'" in msg


def test_check_benchmark_file_fails_on_missing_file(tmp_path):
    ok, msg, _ = checker.check_benchmark_file(tmp_path / "nonexistent.jsonl")
    assert ok is False
    assert "not found" in msg
