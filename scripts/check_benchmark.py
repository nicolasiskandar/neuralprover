#!/usr/bin/env python3
"""Check the benchmark generation and proof-search evaluation pipeline end to end.

This packages the benchmark workflow that was previously run as ad-hoc commands:
- Benchmark file integrity (file existence, row count, single/multi-step balance, schema)
- CLI registration for replay-corpus and evaluate subcommands
- Pass@k metrics calculation sanity checks
- Optional Lean elaboration and bounded proof-search smoke tests

Usage:
    python scripts/check_benchmark.py
    python scripts/check_benchmark.py --benchmark data/benchmarks/mathlib-test-50.jsonl
    python scripts/check_benchmark.py --run-lean-search --theorems 2
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from neuralproof.evaluation.metrics import pass_at_k, summarize
from neuralproof.lean.client import LeanClient
from neuralproof.search.best_first import best_first
from neuralproof.models.predictor import StaticPredictor

DEFAULT_BENCHMARK = REPO_ROOT / "data" / "benchmarks" / "mathlib-test-50.jsonl"
DEFAULT_MANIFEST = REPO_ROOT / "data" / "benchmarks" / "manifest.json"


def check_cli_subcommands() -> tuple[bool, str]:
    """Verify that 'replay-corpus' and 'evaluate' subcommands are registered in CLI."""
    proc = subprocess.run(
        [sys.executable, "-m", "neuralproof.cli", "data", "--help"],
        capture_output=True,
        text=True,
    )
    if "replay-corpus" not in proc.stdout:
        return False, "replay-corpus subcommand missing from 'data --help'"

    proc_eval = subprocess.run(
        [sys.executable, "-m", "neuralproof.cli", "evaluate", "--help"],
        capture_output=True,
        text=True,
    )
    if proc_eval.returncode != 0:
        return False, "'evaluate --help' failed"

    return True, "CLI subcommands 'replay-corpus' and 'evaluate' verified"


def check_metrics_estimator() -> tuple[bool, str]:
    """Verify pass@k implementation against reference values."""
    # c=0 -> 0.0
    if pass_at_k(10, 0, 1) != 0.0:
        return False, "pass@k failed: 0 successes should yield 0.0"
    # c=n -> 1.0
    if pass_at_k(10, 10, 5) != 1.0:
        return False, "pass@k failed: all successes should yield 1.0"
    # c=2, n=10, k=10 -> 1 - binom(8,10)/binom(10,10) = 1.0
    if pass_at_k(10, 2, 10) != 1.0:
        return False, "pass@k failed: n-c < k should yield 1.0"

    # Test repeat attempts summary
    summ = summarize([
        {"verified": True, "attempts": 10, "verified_attempts": 2},
        {"verified": False, "attempts": 10, "verified_attempts": 0},
    ])
    if summ.get("pass_at_10") != 0.5:
        return False, f"summarize pass_at_10 expected 0.5, got {summ.get('pass_at_10')}"

    return True, "pass_at_k combinatorial estimator and summary logic verified"


def check_benchmark_file(benchmark_path: Path, manifest_path: Path | None = None) -> tuple[bool, str, dict[str, Any]]:
    """Validate benchmark JSONL structure and diversity."""
    if not benchmark_path.exists():
        return False, f"Benchmark file not found: {benchmark_path}", {}

    lines = [l for l in benchmark_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        return False, f"Benchmark file is empty: {benchmark_path}", {}

    rows = []
    required_keys = {"theorem_id", "theorem", "context", "source_file", "source_declaration", "split"}
    for idx, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            return False, f"Row {idx} malformed JSON: {exc}", {}
        missing = required_keys - set(row.keys())
        if missing:
            return False, f"Row {idx} missing required keys: {missing}", {}
        if row.get("split") != "test":
            return False, f"Row {idx} split is '{row.get('split')}', expected 'test'", {}
        rows.append(row)

    single_step = sum(1 for r in rows if r.get("completed_after_first_tactic"))
    multi_step = sum(1 for r in rows if not r.get("completed_after_first_tactic"))
    unique_files = len(set(r.get("source_file") for r in rows))

    stats = {
        "theorems": len(rows),
        "single_step": single_step,
        "multi_step": multi_step,
        "unique_files": unique_files,
    }

    manifest_status = "present" if manifest_path and manifest_path.exists() else "not checked"
    return True, f"Benchmark verified ({len(rows)} theorems, {single_step} single-step, {multi_step} multi-step, {unique_files} files, manifest {manifest_status})", stats


def check_lean_search(theorems_path: Path, count: int = 1) -> tuple[bool, str]:
    """Run LeanClient inspection and bounded best-first search on a subset of theorems."""
    client = LeanClient()
    lines = [l for l in theorems_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [json.loads(l) for l in lines[:count]]

    predictor = StaticPredictor(["rfl", "simp", "assumption"])
    for row in rows:
        thm = row["theorem"]
        ctx = row.get("context", "import Lean")
        state = client.initial_state(thm, context=ctx)
        insp = client.inspect(state)
        if not insp.success:
            return False, f"Lean inspect failed on {row['theorem_id']}: {insp.error[:200]}"

        # Run 1 node best_first search
        res = best_first(client, thm, predictor, context=ctx, max_nodes=2, width=2, timeout=20)
        if res.expanded < 1:
            return False, f"Search failed to expand initial node for {row['theorem_id']}"

    return True, f"Lean elaboration and search smoke test passed on {len(rows)} theorem(s)"


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end sanity check for benchmark and search pipeline.")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK, help="Path to benchmark JSONL")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="Path to benchmark manifest JSON")
    parser.add_argument("--run-lean-search", action="store_true", help="Execute real Lean inspect and search smoke test")
    parser.add_argument("--theorems", type=int, default=1, help="Number of theorems to test with Lean (if enabled)")
    args = parser.parse_args()

    print("=" * 60)
    print("NeuralProof Benchmark & Evaluation Pipeline Check")
    print("=" * 60)

    all_passed = True

    # 1. CLI subcommands check
    ok, msg = check_cli_subcommands()
    print(f"[{'OK' if ok else 'FAIL'}] CLI Subcommands: {msg}")
    all_passed = all_passed and ok

    # 2. Metrics check
    ok, msg = check_metrics_estimator()
    print(f"[{'OK' if ok else 'FAIL'}] Metrics & Pass@k: {msg}")
    all_passed = all_passed and ok

    # 3. Benchmark file check
    ok, msg, stats = check_benchmark_file(args.benchmark, args.manifest)
    print(f"[{'OK' if ok else 'FAIL'}] Benchmark Dataset: {msg}")
    all_passed = all_passed and ok

    # 4. Lean search check (optional or explicit)
    if args.run_lean_search:
        if not ok:
            print("[SKIP] Lean Search: skipped due to missing benchmark file")
        else:
            ok, msg = check_lean_search(args.benchmark, count=args.theorems)
            print(f"[{'OK' if ok else 'FAIL'}] Lean Search Smoke: {msg}")
            all_passed = all_passed and ok
    else:
        print("[SKIP] Lean Search Smoke: pass --run-lean-search to execute with Lean compiler")

    print("-" * 60)
    if all_passed:
        print("ALL CHECKS PASSED.")
        return 0
    else:
        print("SOME CHECKS FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
