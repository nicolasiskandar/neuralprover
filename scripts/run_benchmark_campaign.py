#!/usr/bin/env python3
"""Run multi-configuration proof-search benchmark campaign and generate comparative report.

Evaluates bounded best-first search across:
  1. Static heuristic baseline ('rfl, simp, assumption, exact True.intro')
  2. Base SmolLM2-135M model (zero-shot)
  3. Canonical 1-epoch LoRA adapter
  4. Canonical LoRA adapter + Lemma Filtering

Usage:
    python scripts/run_benchmark_campaign.py
    python scripts/run_benchmark_campaign.py --configs static,lora
    python scripts/run_benchmark_campaign.py --nodes 20 --width 4 --timeout 30
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from neuralproof.evaluation.benchmark import run, theorem_header
from neuralproof.evaluation.metrics import summarize
from neuralproof.lean.client import LeanClient
from neuralproof.models.predictor import StaticPredictor, load_hf_predictor

DEFAULT_BENCHMARK = REPO_ROOT / "data" / "benchmarks" / "mathlib-test-50.jsonl"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "benchmark-50"
DEFAULT_BASE_MODEL = "HuggingFaceTB/SmolLM2-135M"
DEFAULT_REVISION = "4e53f736cbb20a9a0f56b4c4bf378d9f306ff915"
DEFAULT_ADAPTER = REPO_ROOT / "experiments" / "mathlib-info-tree-lora-200-1epoch-canonical"


def format_rate(rate: float | None, interval: list[float] | None = None) -> str:
    if rate is None:
        return "N/A"
    pct = f"{rate * 100:.1f}%"
    if interval and len(interval) == 2:
        return f"{pct} [{interval[0]*100:.1f}%, {interval[1]*100:.1f}%]"
    return pct


def format_num(val: float | None, precision: int = 1) -> str:
    if val is None:
        return "—"
    return f"{val:.{precision}f}"


def build_markdown_report(
    summaries: dict[str, dict[str, Any]],
    theorems: list[dict[str, Any]],
    results_by_config: dict[str, list[dict[str, Any]]],
    budgets: dict[str, Any],
    benchmark_path: str | Path | None = None,
) -> str:
    total = len(theorems)
    single_ids = {r["theorem_id"] for r in theorems if r.get("completed_after_first_tactic")}
    multi_ids = {r["theorem_id"] for r in theorems if not r.get("completed_after_first_tactic")}
    benchmark_line = f"- **Benchmark**: {total} held-out Mathlib theorems"
    if benchmark_path is not None:
        benchmark_line += f" (`{benchmark_path}`)"
    lines = [
        f"# {total}-Theorem Proof-Search Evaluation Campaign",
        "",
        "## Overview",
        "",
        benchmark_line,
        f"- **Search Budget**: `max_nodes={budgets.get('max_nodes', 20)}`, `width={budgets.get('width', 4)}`, `timeout={budgets.get('timeout', 30)}s`",
        f"- **Date**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "## Summary Results",
        "",
        "| Configuration | Attempted | Solved | Solve Rate (Wilson 95%) | Mean Nodes | Mean Calls | Invalid Tactics | Filtered Lemmas | Mean Solve (s) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for name, s in summaries.items():
        attempted = s.get("attempted", 0)
        verified = s.get("verified", 0)
        rate_str = format_rate(s.get("solve_rate"), s.get("solve_rate_wilson95"))
        nodes = format_num(s.get("mean_nodes_expanded"))
        calls = format_num(s.get("mean_tactic_calls"))
        invalid = s.get("invalid_tactics", 0)
        filtered = s.get("rejected_unknown_lemmas", 0)
        solve_sec = format_num(s.get("mean_solve_seconds"))
        lines.append(
            f"| **{name}** | {attempted} | {verified} | {rate_str} | {nodes} | {calls} | {invalid} | {filtered} | {solve_sec} |"
        )

    lines.extend([
        "",
        "## Stratified Performance by Proof Depth",
        "",
        f"| Configuration | Single-Step Solved (of {len(single_ids)}) | "
        f"Multi-Step Solved (of {len(multi_ids)}) | Overall Solved (of {total}) |",
        "| :--- | :---: | :---: | :---: |",
    ])

    for name, res_list in results_by_config.items():
        res_map = {r["theorem_id"]: r.get("verified", False) for r in res_list}
        single_solved = sum(1 for tid in single_ids if res_map.get(tid))
        multi_solved = sum(1 for tid in multi_ids if res_map.get(tid))
        total_solved = single_solved + multi_solved
        single_pct = f"{single_solved / len(single_ids) * 100:.1f}%" if single_ids else "N/A"
        multi_pct = f"{multi_solved / len(multi_ids) * 100:.1f}%" if multi_ids else "N/A"
        total_pct = f"{total_solved / len(theorems) * 100:.1f}%" if theorems else "N/A"
        lines.append(
            f"| **{name}** | {single_solved} / {len(single_ids)} ({single_pct}) | "
            f"{multi_solved} / {len(multi_ids)} ({multi_pct}) | "
            f"{total_solved} / {len(theorems)} ({total_pct}) |"
        )

    lines.extend([
        "",
        "## Solved Theorems Detail",
        "",
    ])

    any_solved = False
    for r in theorems:
        tid = r["theorem_id"]
        solved_by = [
            cfg_name
            for cfg_name, res_list in results_by_config.items()
            if any(item["theorem_id"] == tid and item.get("verified") for item in res_list)
        ]
        if solved_by:
            any_solved = True
            lines.append(f"- **`{r['source_declaration']}`** (`{r['source_file']}`)")
            lines.append(f"  - Depth: {r.get('proof_depth')}, Solved by: {', '.join(f'`{c}`' for c in solved_by)}")

    if not any_solved:
        lines.append("*No theorems were solved under the current search budget across configurations.*")

    lines.append("")
    return "\n".join(lines)


def run_campaign(
    theorems: list[dict[str, Any]],
    client: Any,
    configs_to_run: list[str],
    output_dir: Path,
    *,
    base_model: str = DEFAULT_BASE_MODEL,
    revision: str = DEFAULT_REVISION,
    adapter: Path = DEFAULT_ADAPTER,
    max_nodes: int = 20,
    width: int = 4,
    timeout: float = 30,
    benchmark_path: Path | str | None = None,
) -> tuple[dict[str, dict[str, Any]], str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict[str, Any]] = {}
    results_by_config: dict[str, list[dict[str, Any]]] = {}

    budget = {"max_nodes": max_nodes, "width": width, "timeout": timeout}

    # Cache models across configurations
    cached_base_predictor = None
    cached_lora_predictor = None

    for config_name in configs_to_run:
        print(f"\n{'='*60}\nRunning Configuration: {config_name}\n{'='*60}")
        cfg_out_dir = output_dir / config_name
        cfg_out_dir.mkdir(parents=True, exist_ok=True)
        out_file = cfg_out_dir / "results.jsonl"

        filter_invalid = False
        if config_name == "static":
            predictor = StaticPredictor(["rfl", "simp", "assumption", "exact True.intro"])
        elif config_name == "base":
            if cached_base_predictor is None:
                print(f"Loading Base Model: {base_model} ({revision[:8]})...")
                cached_base_predictor = load_hf_predictor(base_model, revision=revision)
            predictor = cached_base_predictor
        elif config_name == "lora":
            if cached_lora_predictor is None:
                print(f"Loading Canonical LoRA Adapter: {adapter}...")
                cached_lora_predictor = load_hf_predictor(base_model, adapter=str(adapter), revision=revision)
            predictor = cached_lora_predictor
        elif config_name == "lora_filtered":
            if cached_lora_predictor is None:
                print(f"Loading Canonical LoRA Adapter: {adapter}...")
                cached_lora_predictor = load_hf_predictor(base_model, adapter=str(adapter), revision=revision)
            predictor = cached_lora_predictor
            filter_invalid = True
        else:
            raise ValueError(f"Unknown config: {config_name}")

        start_time = time.monotonic()
        run_results = run(
            theorems,
            client,
            predictor,
            out_file,
            filter_invalid_lemmas=filter_invalid,
            **budget,
        )
        elapsed = time.monotonic() - start_time

        cfg_summary = summarize(run_results)
        cfg_summary["wall_seconds"] = elapsed
        summaries[config_name] = cfg_summary
        results_by_config[config_name] = run_results

        # Write summary JSON
        (cfg_out_dir / "summary.json").write_text(json.dumps(cfg_summary, indent=2) + "\n")
        print(f"Finished {config_name} in {elapsed:.1f}s: "
              f"Solved {cfg_summary['verified']}/{cfg_summary['attempted']} "
              f"({format_rate(cfg_summary['solve_rate'])})")

    # Generate consolidated Markdown report
    report_md = build_markdown_report(summaries, theorems, results_by_config, budget,
                                      benchmark_path=benchmark_path)
    report_path = output_dir / "report.md"
    report_path.write_text(report_md)

    comparison_path = output_dir / "comparison.json"
    comparison_data = {
        "budgets": budget,
        "theorems_count": len(theorems),
        "summaries": summaries,
    }
    comparison_path.write_text(json.dumps(comparison_data, indent=2) + "\n")

    return summaries, report_md


def main():
    p = argparse.ArgumentParser(description="Run 50-theorem proof-search evaluation campaign.")
    p.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK, help="Path to benchmark JSONL")
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Destination directory for campaign")
    p.add_argument("--configs", default="static,base,lora,lora_filtered", help="Comma-separated configs to run")
    p.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    p.add_argument("--revision", default=DEFAULT_REVISION)
    p.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    p.add_argument("--nodes", type=int, default=20)
    p.add_argument("--width", type=int, default=4)
    p.add_argument("--timeout", type=float, default=30)
    p.add_argument("--theorems-limit", type=int, default=0, help="Optional subset of theorems (0 = all)")
    args = p.parse_args()

    lines = [l for l in args.benchmark.read_text(encoding="utf-8").splitlines() if l.strip()]
    theorems = [json.loads(l) for l in lines]
    if args.theorems_limit > 0:
        theorems = theorems[: args.theorems_limit]

    print(f"Loaded {len(theorems)} benchmark theorems from {args.benchmark}")
    client = LeanClient()
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]

    summaries, report_md = run_campaign(
        theorems,
        client,
        configs,
        args.output_dir,
        base_model=args.base_model,
        revision=args.revision,
        adapter=args.adapter,
        max_nodes=args.nodes,
        width=args.width,
        timeout=args.timeout,
        benchmark_path=args.benchmark,
    )

    print("\n" + "=" * 60)
    print("CAMPAIGN REPORT PREVIEW:")
    print("=" * 60)
    print(report_md)


if __name__ == "__main__":
    main()
