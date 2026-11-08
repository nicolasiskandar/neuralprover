"""Resumable staged Mathlib extraction using native Lean InfoTree traces."""
from __future__ import annotations

import hashlib
import argparse
import json
import re
from pathlib import Path
from typing import Any

from neuralproof.data.extraction import MATHLIB_REVISION
from neuralproof.data.info_tree import trace_file
from neuralproof.data.normalize_info_tree import normalize_trace


def _is_broad_import_context(context: str) -> bool:
    """True when the context has an exact `import Mathlib` line.

    A trailing newline is not required, and a narrower import such as
    `import Mathlib.Tactic` is not counted as the broad library import.
    """
    return any(
        re.fullmatch(r"(?:public\s+|meta\s+)?import\s+Mathlib", line.strip())
        for line in context.splitlines()
    )


def _write_json(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def extract_info_tree_corpus(mathlib_root: Path, output: Path, *, files: int = 200,
                             seed: str = "neuralproof-v1", timeout: float = 300,
                             per_file: int = 0, resume: bool = True) -> dict[str, Any]:
    """Trace a deterministic Mathlib file tranche and checkpoint each result.

    `per_file=0` keeps every normalized tactic example. Failed file traces are
    recorded and checkpointed so one unsupported module does not lose progress.
    """
    if files < 1 or per_file < 0 or timeout <= 0:
        raise ValueError("files and timeout must be positive; per_file cannot be negative")
    mathlib_root = mathlib_root.resolve()
    selected_paths = sorted((mathlib_root / "Mathlib").rglob("*.lean"))[:files]
    selected = [p.relative_to(mathlib_root).as_posix() for p in selected_paths]
    if not selected:
        raise FileNotFoundError(f"No Mathlib source files under {mathlib_root / 'Mathlib'}")

    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "backend": "lean4_info_tree_normalized",
        "source": "Mathlib",
        "mathlib_revision": MATHLIB_REVISION,
        "selection": "first N paths in sorted Mathlib/**/*.lean order",
        "requested_files": files,
        "selected_files": len(selected),
        "file_list_sha256": hashlib.sha256("\n".join(selected).encode()).hexdigest(),
        "split_seed": seed,
        "per_file_example_cap": per_file,
        "timeout_seconds": timeout,
        "context_policy": "source_imports_and_active_context_excluding_target",
        "validation_policy": "original_file_elaborated; reconstructed_context_not_replayed",
    }
    manifest_path = output / "manifest.json"
    if manifest_path.exists() and resume:
        old = json.loads(manifest_path.read_text())
        changed = [k for k, v in manifest.items() if old.get(k) != v]
        if changed:
            raise ValueError("existing InfoTree corpus manifest differs in " + ", ".join(changed))
    _write_json(manifest_path, manifest)

    examples_path, stats_path = output / "examples.jsonl", output / "file_stats.jsonl"
    completed_path = output / "completed.json"
    if not resume:
        examples_path.write_text("")
        stats_path.write_text("")
        _write_json(completed_path, {"files": []})
    completed = set(json.loads(completed_path.read_text()).get("files", [])) if resume and completed_path.exists() else set()
    examples = [json.loads(line) for line in examples_path.read_text().splitlines() if line.strip()] if resume and examples_path.exists() else []
    known = {row["example_id"] for row in examples}
    stats_by_file: dict[str, dict[str, Any]] = {}
    if resume and stats_path.exists():
        for line in stats_path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                stats_by_file[row["source_file"]] = row

    for index, relative in enumerate(selected, 1):
        if relative in completed:
            continue
        print(f"[{index}/{len(selected)}] {relative}", flush=True)
        source = mathlib_root / relative
        try:
            trace = trace_file(source, timeout=timeout)
            rows, stats = normalize_trace(trace, source, seed=seed)
            if per_file:
                stats["normalized_before_cap"] = len(rows)
                rows = rows[:per_file]
            stats["status"] = "ok"
            stats["file_index"] = index
            with examples_path.open("a", encoding="utf-8") as sink:
                for row in rows:
                    if row["example_id"] not in known:
                        sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                        known.add(row["example_id"])
                        examples.append(row)
        except Exception as exc:  # preserve failures as data and continue the tranche
            stats = {"source_file": relative, "source_revision": MATHLIB_REVISION,
                     "file_index": index, "status": "error", "error": f"{type(exc).__name__}: {exc}",
                     "input_nodes": 0, "output_examples": 0}
        stats["source_file"] = relative
        stats_by_file[relative] = stats
        temp_stats = stats_path.with_suffix(stats_path.suffix + ".tmp")
        temp_stats.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n"
                                               for _, item in sorted(stats_by_file.items())))
        temp_stats.replace(stats_path)
        completed.add(relative)
        _write_json(completed_path, {"files": sorted(completed), "last_file": relative})

    examples = ([json.loads(line) for line in examples_path.read_text().splitlines() if line.strip()]
                if examples_path.exists() else [])
    counts = {name: sum(row.get("split") == name for row in examples)
              for name in ("train", "validation", "test")}
    split_files = {name: len({row["source_file"] for row in examples if row.get("split") == name})
                   for name in ("train", "validation", "test")}
    split_declarations = {name: {row["source_declaration"] for row in examples
                                 if row.get("split") == name}
                          for name in ("train", "validation", "test")}
    declaration_overlap = sum(bool(split_declarations[a] & split_declarations[b])
                              for i, a in enumerate(("train", "validation", "test"))
                              for b in ("train", "validation", "test")[i + 1:])
    status_counts = {name: sum(row.get("status") == name for row in stats_by_file.values())
                     for name in ("ok", "error")}
    failed_files = [{"source_file": name, "error": row.get("error", "")}
                    for name, row in sorted(stats_by_file.items()) if row.get("status") == "error"]
    summary = {**manifest, "completed_files": len(completed), "file_status": status_counts,
               "examples": len(examples), "split_examples": counts,
               "split_source_files": split_files,
               "cross_split_declaration_name_overlap_pairs": declaration_overlap,
               "failed_files": failed_files,
               "files_with_examples": len({row["source_file"] for row in examples}),
               "duplicate_example_ids": len(examples) - len({row["example_id"] for row in examples}),
               "broad_import_context_rows": sum(_is_broad_import_context(row["context"]) for row in examples)}
    _write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mathlib-root", type=Path, default=Path("lean/.lake/packages/mathlib"))
    parser.add_argument("--output", type=Path, default=Path("data/mathlib-info-tree-200"))
    parser.add_argument("--files", type=int, default=200)
    parser.add_argument("--per-file", type=int, default=0)
    parser.add_argument("--seed", default="neuralproof-v1")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    result = extract_info_tree_corpus(args.mathlib_root, args.output, files=args.files,
                                      per_file=args.per_file, seed=args.seed,
                                      timeout=args.timeout, resume=not args.no_resume)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
