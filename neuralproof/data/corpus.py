#!/usr/bin/env python3
"""Resumable, deterministic Mathlib extraction over a bounded file tranche.

The current extractor replays a conservative subset of declarations through Lean.
Every accepted target tactic is therefore real and kernel checked. Unsupported
syntax and replay failures remain visible in the stats stream.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from neuralproof.data.extraction import MATHLIB_REVISION, extract_mathlib_file
from neuralproof.data.splits import split_for
from neuralproof.lean.client import LeanClient


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def _normalized_id(row: dict[str, Any]) -> str:
    safe_file = re.sub(r"[^A-Za-z0-9_]", "_", row["source_file"].replace(".lean", ""))
    safe_decl = re.sub(r"[^A-Za-z0-9_]", "_", row["source_declaration"])
    return f"np_mined_{safe_file}_{safe_decl}"


def extract_corpus(mathlib_root: Path, output: Path, *, files: int = 200,
                   per_file: int = 5, seed: str = "neuralproof-v1",
                   resume: bool = True) -> dict[str, Any]:
    if files < 1 or per_file < 1:
        raise ValueError("files and per_file must both be positive")
    all_files = sorted((mathlib_root / "Mathlib").rglob("*.lean"))
    selected = [p.relative_to(mathlib_root).as_posix() for p in all_files[:files]]
    if not selected:
        raise FileNotFoundError(f"No Mathlib source files under {mathlib_root / 'Mathlib'}")
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    file_hash = hashlib.sha256("\n".join(selected).encode()).hexdigest()
    manifest = {
        "schema_version": 3,
        "backend": "lean_replay_subset",
        "context_policy": "source_imports_and_active_context_excluding_target",
        "theorem_id_policy": "source_file_and_qualified_declaration",
        "source": "Mathlib",
        "mathlib_revision": MATHLIB_REVISION,
        "split_seed": seed,
        "selection": "first N paths in sorted Mathlib/**/*.lean order",
        "requested_files": files,
        "selected_files": len(selected),
        "file_list_sha256": file_hash,
        "per_file_example_cap": per_file,
    }
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if resume:
            migratable = {"schema_version", "theorem_id_policy"}
            changed = [key for key, value in manifest.items()
                       if key not in migratable and old.get(key) != value]
            if changed:
                raise ValueError("existing corpus manifest differs in " + ", ".join(changed) + "; choose a new output or disable resume")
    _write_json(manifest_path, manifest)

    rows_path, stats_path = output / "examples.jsonl", output / "file_stats.jsonl"
    completed_path = output / "completed.json"
    completed = set(json.loads(completed_path.read_text()).get("files", [])) if resume and completed_path.exists() else set()
    if not resume:
        rows_path.write_text("")
        stats_path.write_text("")
        _write_json(completed_path, {"files": []})
    valid_rows: list[dict[str, Any]] = []
    if rows_path.exists() and resume:
        source_lines = [line for line in rows_path.read_text().splitlines() if line.strip()]
        original_rows: list[dict[str, Any]] = []
        for line in source_lines:
            try:
                row = json.loads(line)
                original_rows.append(dict(row))
                valid_rows.append(row)
            except (ValueError, KeyError):
                continue
        for row in valid_rows:
            theorem_id = _normalized_id(row)
            if row.get("theorem_id") != theorem_id:
                row["theorem_id"] = theorem_id
                row["theorem"] = re.sub(r"^((?:theorem|lemma)\s+)\S+", lambda m: m.group(1) + theorem_id,
                                        row.get("theorem", ""))
        if valid_rows != original_rows or len(valid_rows) != len(source_lines):
            rows_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in valid_rows))
    known = {(row["source_file"], row["source_declaration"], row["goal_state"], row["target_tactic"])
             for row in valid_rows}
    file_stats: dict[str, dict[str, Any]] = {}
    if stats_path.exists() and resume:
        for line in stats_path.read_text().splitlines():
            try:
                stat = json.loads(line)
                file_stats[stat["source_file"]] = stat
            except (ValueError, KeyError):
                continue
    client = LeanClient()
    for idx, relative in enumerate(selected, start=1):
        if relative in completed:
            continue
        print(f"[{idx}/{len(selected)}] {relative}", flush=True)
        rows, stats = extract_mathlib_file(client, mathlib_root, relative, limit=per_file)
        stats["split"] = split_for(relative, seed)
        stats["file_index"] = idx
        with rows_path.open("a", encoding="utf-8") as sink:
            for row in rows:
                row["split"] = split_for(relative, seed)
                theorem_id = _normalized_id(row)
                row["theorem_id"] = theorem_id
                row["theorem"] = re.sub(r"^((?:theorem|lemma)\s+)\S+", lambda m: m.group(1) + theorem_id,
                                        row.get("theorem", ""))
                key = (row["source_file"], row["source_declaration"], row["goal_state"], row["target_tactic"])
                if key not in known:
                    sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                    known.add(key)
        file_stats[relative] = stats
        temp_stats = stats_path.with_suffix(stats_path.suffix + ".tmp")
        temp_stats.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n"
                                     for _, item in sorted(file_stats.items())))
        temp_stats.replace(stats_path)
        completed.add(relative)
        _write_json(completed_path, {"files": sorted(completed), "last_file": relative})

    rows = [json.loads(line) for line in rows_path.read_text().splitlines() if line.strip()]
    counts = {s: sum(r["split"] == s for r in rows) for s in ("train", "validation", "test")}
    split_files = {s: len({r["source_file"] for r in rows if r["split"] == s})
                   for s in ("train", "validation", "test")}
    declaration_ids = [r["source_declaration"] for r in rows]
    theorem_ids = [r["theorem_id"] for r in rows]
    broad_import_rows = sum(any(line.strip() in {"import Mathlib", "public import Mathlib"}
                                for line in r["context"].splitlines()) for r in rows)
    failure_count = 0
    for line in stats_path.read_text().splitlines():
        if line.strip():
            failure_count += len(json.loads(line).get("failures", []))
    summary = {**manifest, "completed_files": len(completed), "examples": len(rows),
               "split_examples": counts, "failures": failure_count,
               "split_source_files": split_files,
               "files_with_examples": len({r["source_file"] for r in rows}),
               "duplicate_source_declaration_ids": len(declaration_ids) - len(set(declaration_ids)),
               "duplicate_theorem_ids": len(theorem_ids) - len(set(theorem_ids)),
               "broad_import_context_rows": broad_import_rows}
    _write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mathlib-root", type=Path, default=Path("lean/.lake/packages/mathlib"))
    parser.add_argument("--output", type=Path, default=Path("data/mathlib-200"))
    parser.add_argument("--files", type=int, default=200)
    parser.add_argument("--per-file", type=int, default=5)
    parser.add_argument("--seed", default="neuralproof-v1")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    result = extract_corpus(args.mathlib_root, args.output, files=args.files,
                            per_file=args.per_file, seed=args.seed, resume=not args.no_resume)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
