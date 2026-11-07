"""Tests for held-out benchmark theorem dataset construction and validation."""
import gzip
import json
from pathlib import Path

import pytest

from neuralproof.evaluation.benchmark_dataset import (
    build_benchmark_dataset,
    find_statement_matches,
    load_test_declarations,
    synthesize_benchmark_row,
)
from neuralproof.lean.client import ExecutionResult, ProofState


class FakePrevalClient:
    def __init__(self, failing=()):
        self.failing = set(failing)

    def initial_state(self, theorem, context="import Lean"):
        return ProofState(theorem, context)

    def inspect(self, state):
        if state.theorem in self.failing:
            return ExecutionResult(False, None, False, "unknown identifier")
        return ExecutionResult(True, ProofState(state.theorem, state.context, goals=("⊢ True",)), False, "")


def test_load_test_declarations_filters_to_test_split(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    rows = [
        {"split": "train", "source_declaration": "decl_train", "source_file": "A.lean"},
        {
            "split": "test",
            "source_declaration": "decl_test1",
            "source_file": "B.lean",
            "source_start": 10,
            "target_tactic": "simp",
            "completed_after_tactic": True,
        },
        {
            "split": "test",
            "source_declaration": "decl_test1",
            "source_file": "B.lean",
            "source_start": 20,
            "target_tactic": "rfl",
            "completed_after_tactic": True,
        },
        {
            "split": "test",
            "source_declaration": "decl_test2",
            "source_file": "C.lean",
            "source_start": 5,
            "target_tactic": "intro x",
            "completed_after_tactic": False,
        },
    ]
    corpus.write_text("".join(json.dumps(r) + "\n" for r in rows))

    decls = load_test_declarations(corpus)
    assert set(decls.keys()) == {"decl_test1", "decl_test2"}
    assert decls["decl_test1"]["proof_depth"] == 2
    assert decls["decl_test1"]["completed_after_first_tactic"] is True
    assert decls["decl_test1"]["first_tactic"] == "simp"
    assert decls["decl_test2"]["proof_depth"] == 1
    assert decls["decl_test2"]["completed_after_first_tactic"] is False


def test_find_statement_matches_reads_gzipped_jsonl(tmp_path):
    stmts = tmp_path / "statements.jsonl.gz"
    items = [
        {"name": "decl_test1", "type": "∀ (x : Nat), x = x", "module": "Mathlib.A"},
        {"name": "decl_other", "type": "True", "module": "Mathlib.B"},
    ]
    with gzip.open(stmts, "wt") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")

    matches = find_statement_matches(stmts, ["decl_test1", "decl_missing"])
    assert "decl_test1" in matches
    assert "decl_other" not in matches
    assert "decl_missing" not in matches
    assert matches["decl_test1"]["module"] == "Mathlib.A"


def test_synthesize_benchmark_row_formats_cleanly():
    decl_info = {
        "source_file": "Mathlib/Test.lean",
        "proof_depth": 1,
        "first_tactic": "rfl",
        "completed_after_first_tactic": True,
    }
    stmt = {"type": "1 + 1 = 2", "module": "Mathlib.Data.Nat.Basic"}
    row = synthesize_benchmark_row("Nat.test_one", stmt, decl_info)
    assert row.theorem == "theorem np_bench_Nat_test_one : 1 + 1 = 2"
    assert row.context == "import Mathlib.Data.Nat.Basic"
    assert row.source_file == "Mathlib/Test.lean"
    assert row.completed_after_first_tactic is True
    assert row.split == "test"


def test_build_benchmark_dataset_end_to_end_with_mock_client(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    corpus_rows = [
        {"split": "test", "source_declaration": f"decl_{i}", "source_file": f"F{i}.lean",
         "target_tactic": "simp" if i % 2 == 0 else "intro", "completed_after_tactic": (i % 2 == 0)}
        for i in range(10)
    ]
    corpus.write_text("".join(json.dumps(r) + "\n" for r in corpus_rows))

    stmts = tmp_path / "stmts.jsonl"
    stmt_rows = [
        {"name": f"decl_{i}", "type": f"P {i}", "module": f"Mod.{i}"}
        for i in range(10)
    ]
    stmts.write_text("".join(json.dumps(r) + "\n" for r in stmt_rows))

    # decl_0 will fail elaboration
    failing_thm = "theorem np_bench_decl_0 : P 0"
    client = FakePrevalClient(failing=(failing_thm,))

    output = tmp_path / "benchmarks" / "bench.jsonl"
    result = build_benchmark_dataset(
        corpus, stmts, output, total_count=4, single_step_ratio=0.5, seed=123,
        client=client, prevalidate=True
    )

    assert output.exists()
    assert (tmp_path / "benchmarks" / "manifest.json").exists()
    written_rows = [json.loads(l) for l in output.read_text().splitlines() if l.strip()]
    assert len(written_rows) == 4
    # Ensure decl_0 was filtered out
    assert all(r["source_declaration"] != "decl_0" for r in written_rows)
    # Ensure single and multi steps were selected
    assert result["theorems_written"] == 4
