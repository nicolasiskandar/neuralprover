"""Tests for scripts/run_benchmark_campaign.py."""
import json
import importlib.util
import json
from pathlib import Path

import pytest

from neuralproof.lean.client import ExecutionResult, ProofState, VerificationResult

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_campaign():
    path = REPO_ROOT / "scripts" / "run_benchmark_campaign.py"
    spec = importlib.util.spec_from_file_location("run_benchmark_campaign", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


campaign = _load_campaign()
build_markdown_report = campaign.build_markdown_report
run_campaign = campaign.run_campaign


class FakeSearchClient:
    def __init__(self, failing=()):
        self.failing = set(failing)
        self.timeout = 30

    def initial_state(self, theorem, context="import Lean"):
        return ProofState(theorem, context, goals=("⊢ True",))

    def inspect(self, state):
        return ExecutionResult(True, state, False, "")

    def apply(self, state, tactic):
        if tactic in self.failing:
            return ExecutionResult(False, None, False, "unknown tactic")
        return ExecutionResult(True, state, True, "")

    def render_proof(self, state):
        return state.theorem + " := by\n  " + "\n  ".join(state.prefix)

    def verify(self, proof, context="import Lean"):
        return VerificationResult(True, "decl", "", 0.0, ())


def test_build_markdown_report_structures_table():
    summaries = {
        "static": {
            "attempted": 2,
            "verified": 1,
            "solve_rate": 0.5,
            "solve_rate_wilson95": [0.15, 0.85],
            "mean_nodes_expanded": 1.5,
            "mean_tactic_calls": 3.0,
            "invalid_tactics": 1,
            "rejected_unknown_lemmas": 0,
            "mean_solve_seconds": 2.5,
        }
    }
    theorems = [
        {"theorem_id": "t1", "source_declaration": "decl1", "source_file": "A.lean", "completed_after_first_tactic": True, "proof_depth": 1},
        {"theorem_id": "t2", "source_declaration": "decl2", "source_file": "B.lean", "completed_after_first_tactic": False, "proof_depth": 3},
    ]
    results_by_config = {
        "static": [
            {"theorem_id": "t1", "verified": True},
            {"theorem_id": "t2", "verified": False},
        ]
    }
    budgets = {"max_nodes": 20, "width": 4, "timeout": 30}

    report = build_markdown_report(summaries, theorems, results_by_config, budgets)
    assert "# 2-Theorem Proof-Search Evaluation Campaign" in report
    assert ("| Configuration | Single-Step Solved (of 1) | Multi-Step Solved (of 1) "
            "| Overall Solved (of 2) |") in report
    assert "| **static** |" in report
    assert "50.0% [15.0%, 85.0%]" in report
    assert "`decl1`" in report


def test_build_markdown_report_uses_the_actual_theorem_counts():
    summaries = {
        "static": {
            "attempted": 3,
            "verified": 1,
            "solve_rate": 1 / 3,
            "solve_rate_wilson95": [0.1, 0.7],
            "mean_nodes_expanded": 1.0,
            "mean_tactic_calls": 2.0,
            "invalid_tactics": 0,
            "rejected_unknown_lemmas": 0,
            "mean_solve_seconds": 1.0,
        }
    }
    theorems = [
        {"theorem_id": "t1", "source_declaration": "A.t1",
         "source_file": "Mathlib/A.lean", "completed_after_first_tactic": True},
        {"theorem_id": "t2", "source_declaration": "A.t2",
         "source_file": "Mathlib/A.lean", "completed_after_first_tactic": True},
        {"theorem_id": "t3", "source_declaration": "A.t3",
         "source_file": "Mathlib/A.lean", "completed_after_first_tactic": False},
    ]
    results_by_config = {
        "static": [
            {"theorem_id": "t1", "verified": True},
            {"theorem_id": "t2", "verified": False},
            {"theorem_id": "t3", "verified": False},
        ]
    }

    report = build_markdown_report(
        summaries, theorems, results_by_config, {},
        benchmark_path="data/benchmarks/custom.jsonl")

    assert "# 3-Theorem Proof-Search Evaluation Campaign" in report
    assert "(of 2)" in report
    assert "(of 1)" in report
    assert "(of 3)" in report
    assert "(of 25)" not in report
    assert "(of 50)" not in report
    assert "custom.jsonl" in report


def test_run_campaign_executes_static_config(tmp_path):
    theorems = [
        {"theorem_id": "t1", "theorem": "theorem t1 : True", "context": "import Lean", "source_declaration": "t1", "source_file": "A.lean", "completed_after_first_tactic": True, "proof_depth": 1},
    ]
    client = FakeSearchClient()
    out_dir = tmp_path / "campaign_out"

    summaries, report = run_campaign(theorems, client, ["static"], out_dir, max_nodes=2, width=1)
    assert "static" in summaries
    assert summaries["static"]["verified"] == 1
    assert (out_dir / "static" / "results.jsonl").exists()
    assert (out_dir / "static" / "summary.json").exists()
    assert (out_dir / "report.md").exists()
    assert (out_dir / "comparison.json").exists()
