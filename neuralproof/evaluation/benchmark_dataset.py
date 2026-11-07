"""Construction and prevalidation of held-out Mathlib theorem proof-search benchmarks."""
from __future__ import annotations

import gzip
import hashlib
import json
import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from neuralproof.data.provenance import current_command, sha256_file, write_manifest


@dataclass(frozen=True)
class BenchmarkRow:
    theorem_id: str
    theorem: str
    context: str
    source_file: str
    source_declaration: str
    proof_depth: int
    ground_truth_first_tactic: str
    completed_after_first_tactic: bool
    split: str = "test"


def load_test_declarations(corpus_path: Path | str) -> dict[str, dict[str, Any]]:
    """Group test-split InfoTree examples by declaration."""
    path = Path(corpus_path)
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    test_rows = [r for r in rows if r.get("split") == "test"]
    decls: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in test_rows:
        decl = row.get("source_declaration")
        if decl:
            decls[decl].append(row)

    info: dict[str, dict[str, Any]] = {}
    for decl, items in decls.items():
        # Order by start offset if available
        ordered = sorted(items, key=lambda x: (x.get("source_start") or 0, x.get("source_end") or 0))
        first = ordered[0]
        completed_first = bool(first.get("completed_after_tactic", False))
        info[decl] = {
            "source_declaration": decl,
            "source_file": first.get("source_file", ""),
            "proof_depth": len(ordered),
            "first_tactic": first.get("target_tactic", ""),
            "completed_after_first_tactic": completed_first,
        }
    return info


def find_statement_matches(
    statements_path: Path | str, target_declarations: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """Retrieve full typed signatures and module imports for target declarations."""
    targets = set(target_declarations)
    path = Path(statements_path)
    matched: dict[str, dict[str, Any]] = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            item = json.loads(line)
            name = item.get("name")
            if name in targets and name not in matched:
                matched[name] = item
                if len(matched) == len(targets):
                    break
    return matched


def synthesize_benchmark_row(
    decl_name: str, statement_item: dict[str, Any], decl_info: dict[str, Any]
) -> BenchmarkRow:
    """Create a self-contained Lean 4 theorem specification with clean imports."""
    safe_name = "np_bench_" + decl_name.replace(".", "_")
    return BenchmarkRow(
        theorem_id=f"bench_{safe_name}",
        theorem=f"theorem {safe_name} : {statement_item['type']}",
        context=f"import {statement_item['module']}",
        source_file=decl_info["source_file"],
        source_declaration=decl_name,
        proof_depth=decl_info["proof_depth"],
        ground_truth_first_tactic=decl_info["first_tactic"],
        completed_after_first_tactic=decl_info["completed_after_first_tactic"],
        split="test",
    )


def build_benchmark_dataset(
    corpus_path: Path | str,
    statements_path: Path | str,
    output_path: Path | str,
    *,
    total_count: int = 50,
    single_step_ratio: float = 0.5,
    seed: int = 42,
    client: Any | None = None,
    prevalidate: bool = True,
) -> dict[str, Any]:
    """Construct, pre-validate, and write a balanced held-out benchmark suite."""
    corpus_path = Path(corpus_path).resolve()
    statements_path = Path(statements_path).resolve()
    output_path = Path(output_path).resolve()

    decls_info = load_test_declarations(corpus_path)
    matches = find_statement_matches(statements_path, decls_info.keys())

    candidate_rows: list[BenchmarkRow] = []
    for name, stmt in sorted(matches.items()):
        row = synthesize_benchmark_row(name, stmt, decls_info[name])
        candidate_rows.append(row)

    if prevalidate:
        if client is None:
            from neuralproof.lean.client import LeanClient

            client = LeanClient()
        validated: list[BenchmarkRow] = []
        for r in candidate_rows:
            st = client.initial_state(r.theorem, context=r.context)
            res = client.inspect(st)
            if res.success and res.state and res.state.goals:
                validated.append(r)
    else:
        validated = candidate_rows

    single = [r for r in validated if r.completed_after_first_tactic]
    multi = [r for r in validated if not r.completed_after_first_tactic]

    rng = random.Random(seed)
    rng.shuffle(single)
    rng.shuffle(multi)

    target_single = min(len(single), int(round(total_count * single_step_ratio)))
    target_multi = min(len(multi), total_count - target_single)

    selected = single[:target_single] + multi[:target_multi]
    # If one pool was smaller, fill remainder from the other
    if len(selected) < total_count:
        remaining_needed = total_count - len(selected)
        leftover = single[target_single:] + multi[target_multi:]
        selected.extend(leftover[:remaining_needed])

    selected.sort(key=lambda r: (r.source_file, r.source_declaration))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as stream:
        for r in selected:
            stream.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    manifest = {
        "schema_version": 1,
        "artifact": "benchmark_theorems",
        "command": current_command(),
        "input_corpus": {"path": str(corpus_path), "sha256": sha256_file(corpus_path)},
        "input_statements": {"path": str(statements_path), "sha256": sha256_file(statements_path)},
        "output": {"path": str(output_path), "sha256": sha256_file(output_path), "rows": len(selected)},
        "requested_count": total_count,
        "single_step_theorems": sum(1 for r in selected if r.completed_after_first_tactic),
        "multi_step_theorems": sum(1 for r in selected if not r.completed_after_first_tactic),
        "unique_source_files": len(set(r.source_file for r in selected)),
        "seed": seed,
        "prevalidated_by_kernel": prevalidate,
    }
    write_manifest(output_path.parent / "manifest.json", manifest)

    return {
        "theorems_written": len(selected),
        "single_step": sum(1 for r in selected if r.completed_after_first_tactic),
        "multi_step": sum(1 for r in selected if not r.completed_after_first_tactic),
        "output": str(output_path),
        "manifest": str(output_path.parent / "manifest.json"),
    }
