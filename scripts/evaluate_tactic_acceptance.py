#!/usr/bin/env python3
"""Measure kernel-checked tactic acceptance on held-out predictions.

This is the packaged form of the acceptance plan: load the existing held-out
predictions, self-check each original source transition, substitute each model
prediction at the same position, and classify Lean's response.  No model is
loaded and no prompt or checkpoint is changed.

A fragment target (for example a lemma name inside ``simp_rw [...]``) is
substituted into its enclosing tactic rather than being treated as a complete
tactic.  Remaining goals are closed with ``sorry`` so the harness can finish
elaborating; a successful run is tactic acceptance, not a proof of the
declaration.

    python scripts/evaluate_tactic_acceptance.py --limit 12 --sample-by family
    python scripts/evaluate_tactic_acceptance.py --workers 4
    python scripts/evaluate_tactic_acceptance.py --models lora --strict

``results.jsonl`` is written incrementally and resumed by default.  Rerun the
same command after an interruption; pass ``--no-resume`` or ``--force`` to
recompute selected rows.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from neuralproof.data.extraction import MATHLIB_REVISION  # noqa: E402
from neuralproof.data.provenance import code_revision  # noqa: E402
from neuralproof.evaluation.tactic_acceptance import (  # noqa: E402
    aggregate,
    process_row,
    sample_rows,
    select_rows,
    write_report,
)
from neuralproof.lean.transition import TraceCache  # noqa: E402

DEFAULT_EXAMPLES = REPO_ROOT / "data" / "mathlib-info-tree-200" / "examples.jsonl"
DEFAULT_EVAL = (REPO_ROOT / "experiments"
                / "mathlib-info-tree-lora-200-1epoch-canonical"
                / "tactic-eval-full-heldout.json")
DEFAULT_OUTPUT = REPO_ROOT / "experiments" / "tactic-acceptance"
DEFAULT_TRACE_CACHE = REPO_ROOT / "data" / "cache" / "info-tree-traces"


def read_results(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return records
    with path.open() as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            example_id = record.get("example_id")
            if example_id:
                records[str(example_id)] = record
    return records


def _complete(record: dict[str, Any], item: dict[str, Any],
              models: list[str]) -> bool:
    if not isinstance(record.get("models"), dict):
        return False
    if "self_check" not in record or "transition" not in record:
        return False
    if any(model not in record["models"] for model in models):
        return False
    row = item["row"]
    return (record.get("source_file") == row.get("source_file")
            and record.get("target") == row.get("target_tactic"))


def _failed_record(item: dict[str, Any], models: list[str],
                   error: Exception) -> dict[str, Any]:
    row = item["row"]
    message = f"internal_error: {type(error).__name__}: {error}"
    return {
        "example_id": row.get("example_id", ""),
        "source_file": row.get("source_file", ""),
        "source_declaration": row.get("source_declaration", ""),
        "source_line": row.get("source_line"),
        "syntax_kind": row.get("syntax_kind", ""),
        "target": row.get("target_tactic", ""),
        "family": "",
        "transition": {"target_kind": "unknown", "is_fragment": None,
                       "reason": message},
        "self_check": {"status": "unsupported", "reason": message,
                       "elapsed_seconds": 0.0},
        "models": {
            model: {
                "prediction": item["predictions"][model],
                "produced_output": bool(item["predictions"][model]),
                "exact_match": bool(item["exact_match"].get(model)),
                "status": "unsupported",
                "reason": message,
                "elapsed_seconds": 0.0,
            }
            for model in models
        },
    }


def _write_record(stream, record: dict[str, Any], lock: threading.Lock) -> None:
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with lock:
        stream.write(line)
        stream.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--examples", type=Path, default=DEFAULT_EXAMPLES)
    parser.add_argument("--eval", type=Path, default=DEFAULT_EVAL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--models", nargs="+", default=["base", "lora"],
                        help="eval sections to check (default: base lora)")
    parser.add_argument("--limit", type=int, default=0,
                        help="check only N rows (0 = all)")
    parser.add_argument("--sample-by", choices=("family", "file", "none"),
                        default="none",
                        help="deterministic stratification for --limit")
    parser.add_argument("--timeout", type=float, default=180.0,
                        help="timeout per Lean harness run")
    parser.add_argument("--trace-timeout", type=float, default=300.0,
                        help="timeout per InfoTree trace regeneration")
    parser.add_argument("--workers", type=int, default=4,
                        help="parallel Lean runs (default: 4)")
    parser.add_argument("--trace-cache", type=Path, default=DEFAULT_TRACE_CACHE)
    parser.add_argument("--refresh-traces", action="store_true",
                        help="regenerate every InfoTree trace instead of using the cache")
    parser.add_argument("--no-resume", action="store_true",
                        help="recompute selected rows instead of reading results.jsonl")
    parser.add_argument("--force", action="store_true",
                        help="clear existing results and report artifacts before running")
    parser.add_argument("--json", nargs="?", const=True, default=False,
                        metavar="PATH",
                        help="print the JSON report; with PATH, also write it there")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero when any selected row is unsupported")
    args = parser.parse_args(argv)

    if not args.examples.is_file():
        parser.error(f"--examples not found: {args.examples}")
    if not args.eval.is_file():
        parser.error(f"--eval not found: {args.eval}")
    if args.timeout <= 0 or args.trace_timeout <= 0:
        parser.error("timeouts must be positive")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    models = list(dict.fromkeys(args.models))

    try:
        rows = select_rows(args.examples, args.eval, models)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    if not rows:
        parser.error("no held-out rows selected")
    selected = sample_rows(rows, args.limit, args.sample_by)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    results_path = output / "results.jsonl"
    if args.force:
        for name in ("results.jsonl", "report.json", "report.md"):
            (output / name).unlink(missing_ok=True)
    elif args.no_resume:
        results_path.unlink(missing_ok=True)

    existing = {} if (args.no_resume or args.force) else read_results(results_path)
    pending = [item for item in selected
               if not _complete(existing.get(item["example_id"], {}), item, models)]

    cache = TraceCache(project_dir=REPO_ROOT / "lean",
                       cache_dir=args.trace_cache,
                       refresh=args.refresh_traces,
                       timeout=args.trace_timeout)
    traces: dict[str, dict[str, Any]] = {}
    source_paths: dict[str, Path] = {}
    for source_file in sorted({item["row"]["source_file"] for item in pending}):
        try:
            traces[source_file] = cache.get(source_file)
            source_paths[source_file] = cache.source_path(source_file)
        except (FileNotFoundError, RuntimeError, OSError) as error:
            raise SystemExit(
                f"cannot load or generate an InfoTree trace for {source_file}: {error}")

    new_records: dict[str, dict[str, Any]] = {}
    with results_path.open("a") as stream:
        lock = threading.Lock()
        if pending:
            print(f"checking {len(pending)} row(s) with {args.workers} worker(s); "
                  f"{len(selected) - len(pending)} resumed from {results_path}")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(process_row, item, traces[item["row"]["source_file"]],
                            source_paths[item["row"]["source_file"]],
                            models=models,
                            project_dir=REPO_ROOT / "lean",
                            timeout=args.timeout): item
                for item in pending
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    record = future.result()
                except Exception as error:  # keep a partial run inspectable
                    record = _failed_record(item, models, error)
                new_records[record["example_id"]] = record
                _write_record(stream, record, lock)

    combined = {**existing, **new_records}
    records = [combined[item["example_id"]] for item in selected
               if item["example_id"] in combined]
    if len(records) != len(selected):
        missing = [item["example_id"] for item in selected
                   if item["example_id"] not in combined]
        raise SystemExit("missing result rows: " + ", ".join(missing[:5]))
    # Canonicalize the resume file in selection order, even when no Lean run
    # was needed on this invocation.
    results_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n"
                for record in records))

    payload: dict[str, Any] = {
        "protocol": {
            "examples": str(args.examples),
            "eval": str(args.eval),
            "models": models,
            "selection": "exact example ids from the eval section",
            "sample_by": args.sample_by,
            "limit": args.limit,
            "timeout_seconds": args.timeout,
            "trace_timeout_seconds": args.trace_timeout,
            "workers": args.workers,
            "trace_cache": str(args.trace_cache),
            "traces_loaded": sorted(set(cache.loaded)),
            "traces_generated": sorted(set(cache.generated)),
            "source_revision": MATHLIB_REVISION,
            "lean_toolchain": (REPO_ROOT / "lean" / "lean-toolchain").read_text().strip(),
            "code_revision": code_revision(),
            "harness": "substitute into the smallest enclosing tactic; close remaining goals with all_goals sorry",
            "self_check": "original source target must close under all_goals sorry",
            "caveat": "tactic acceptance is a diagnostic; Lean is the authority and this is not a proof-solving result",
        },
        "rows": len(records),
        **aggregate(records, models),
        "examples": records,
    }
    report_json, report_md = write_report(output, payload)

    json_path = Path(args.json) if isinstance(args.json, str) else None
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Rows: {len(records)}; models: {', '.join(models)}")
        for model in models:
            summary = payload["models"][model]
            counts = summary["status_counts"]
            print(f"{model:6s} closed={counts['closed']:3d} "
                  f"accepted={counts['accepted']:3d} "
                  f"rejected={counts['rejected']:3d} "
                  f"empty={counts['empty']:3d} "
                  f"timeout={counts['timeout']:3d} "
                  f"unsupported={counts['unsupported']:3d} "
                  f"accepted+closed={summary['accepted_or_closed']}/"
                  f"{summary['supported_rows']} "
                  f"({summary['acceptance_rate_supported'] or 0.0:.1%})")
        print(f"Results written to {results_path}")
        print(f"Report written to {report_json} and {report_md}")

    unsupported = sum(
        record["models"][model]["status"] == "unsupported"
        for record in records for model in models)
    if args.strict and unsupported:
        print(f"STRICT: {unsupported} model-row result(s) are unsupported")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
