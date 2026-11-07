#!/usr/bin/env python3
"""Build a held-out Mathlib theorem benchmark from InfoTree test examples."""
import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from neuralproof.evaluation.benchmark_dataset import build_benchmark_dataset
from neuralproof.lean.client import LeanClient


def main():
    p = argparse.ArgumentParser(description="Construct held-out proof-search benchmark.")
    p.add_argument(
        "--corpus",
        default="data/mathlib-info-tree-200/examples.jsonl",
        help="Path to InfoTree examples.jsonl containing test split rows",
    )
    p.add_argument(
        "--statements",
        default="data/lemma_statements.jsonl.gz",
        help="Path to lemma_statements.jsonl.gz with declaration types",
    )
    p.add_argument(
        "--output",
        default="data/benchmarks/mathlib-test-50.jsonl",
        help="Destination path for benchmark JSONL",
    )
    p.add_argument("--count", type=int, default=50, help="Number of benchmark theorems")
    p.add_argument("--single-ratio", type=float, default=0.5, help="Target ratio of single-step theorems")
    p.add_argument("--seed", type=int, default=42, help="Deterministic sampling seed")
    p.add_argument("--no-prevalidate", action="store_true", help="Skip LeanClient inspect check")
    args = p.parse_args()

    client = None if args.no_prevalidate else LeanClient()
    result = build_benchmark_dataset(
        args.corpus,
        args.statements,
        args.output,
        total_count=args.count,
        single_step_ratio=args.single_ratio,
        seed=args.seed,
        client=client,
        prevalidate=not args.no_prevalidate,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
