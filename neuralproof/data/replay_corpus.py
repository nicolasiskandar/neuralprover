"""Resumable source-context replay for an existing InfoTree JSONL corpus."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from neuralproof.data.extraction import MATHLIB_REVISION
from neuralproof.data.info_tree import trace_file
from neuralproof.data.normalize_info_tree import normalize_trace, validate_trace_examples


def _checkpoint(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def replay_corpus(input_file: Path, mathlib_root: Path, output: Path, *,
                  files: int = 0, timeout: float = 300, resume: bool = True) -> dict[str, Any]:
    if files < 0 or timeout <= 0:
        raise ValueError("files cannot be negative and timeout must be positive")
    input_file, mathlib_root, output = input_file.resolve(), mathlib_root.resolve(), output.resolve()
    source_rows = [json.loads(line) for line in input_file.read_text().splitlines() if line.strip()]
    by_file: dict[str, list[dict[str, Any]]] = {}
    for row in source_rows:
        by_file.setdefault(row["source_file"], []).append(row)
    selected = sorted(by_file)
    if files:
        selected = selected[:files]
    digest = hashlib.sha256(input_file.read_bytes()).hexdigest()
    manifest = {"schema_version": 1, "backend": "lean4_info_tree_replay",
                "input": str(input_file), "input_sha256": digest,
                "mathlib_revision": MATHLIB_REVISION,
                "selection": selected, "selected_files": len(selected),
                "timeout_seconds": timeout}
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    if manifest_path.exists() and resume:
        old = json.loads(manifest_path.read_text())
        changed = [key for key, value in manifest.items() if old.get(key) != value]
        if changed:
            raise ValueError("existing replay manifest differs in " + ", ".join(changed))
    _checkpoint(manifest_path, manifest)
    rows_path, stats_path, done_path = (output / "examples.jsonl", output / "file_stats.jsonl",
                                        output / "completed.json")
    if not resume:
        rows_path.write_text(""); stats_path.write_text("")
        _checkpoint(done_path, {"files": []})
    done = set(json.loads(done_path.read_text()).get("files", [])) if done_path.exists() else set()
    written = {json.loads(line)["example_id"] for line in rows_path.read_text().splitlines() if line.strip()} if rows_path.exists() else set()
    stats_by_file = {x["source_file"]: x for x in
                     (json.loads(line) for line in stats_path.read_text().splitlines() if line.strip())} if stats_path.exists() else {}

    for index, relative in enumerate(selected, 1):
        if relative in done:
            continue
        print(f"[{index}/{len(selected)}] {relative}", flush=True)
        source = Path(relative) if Path(relative).is_absolute() else mathlib_root / relative
        wanted = by_file[relative]
        try:
            trace = trace_file(source, timeout=timeout)
            normalized, _ = normalize_trace(trace, source)
            validated, validation_stats = validate_trace_examples(trace, source, normalized,
                                                                    timeout=timeout)
            available = {row["example_id"]: row for row in validated}
            output_rows = []
            missing = 0
            for row in wanted:
                result = available.get(row["example_id"])
                if result is None:
                    missing += 1
                    output_rows.append({**row, "validation": "failed",
                                        "validation_reason": "example_id_missing_from_current_trace"})
                else:
                    output_rows.append({**result, "split": row.get("split", result.get("split"))})
            status = "ok" if not missing else "partial"
            file_stats = {"source_file": relative, "status": status,
                          "requested_rows": len(wanted), "missing_rows": missing,
                          "validation": validation_stats}
            with rows_path.open("a", encoding="utf-8") as stream:
                for row in output_rows:
                    if row["example_id"] not in written:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                        written.add(row["example_id"])
        except Exception as exc:
            file_stats = {"source_file": relative, "status": "error",
                          "requested_rows": len(wanted),
                          "error": f"{type(exc).__name__}: {exc}"}
            with rows_path.open("a", encoding="utf-8") as stream:
                for row in wanted:
                    if row["example_id"] not in written:
                        stream.write(json.dumps({**row, "validation": "failed",
                                                 "validation_reason": file_stats["error"]},
                                                ensure_ascii=False) + "\n")
                        written.add(row["example_id"])
        stats_by_file[relative] = file_stats
        tmp_stats = stats_path.with_suffix(stats_path.suffix + ".tmp")
        tmp_stats.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n"
                                    for _, x in sorted(stats_by_file.items())))
        tmp_stats.replace(stats_path)
        done.add(relative)
        _checkpoint(done_path, {"files": sorted(done), "last_file": relative})

    output_rows = [json.loads(line) for line in rows_path.read_text().splitlines() if line.strip()]
    summary = {**manifest, "completed_files": sum(x in done for x in selected),
               "file_status": {status: sum(x.get("status") == status for x in stats_by_file.values())
                               for status in ("ok", "partial", "error")},
               "input_rows": sum(len(by_file[x]) for x in selected),
               "written_rows": len(output_rows),
               "replay_rows": sum(x.get("validation") == "replayed" for x in output_rows),
               "declaration_rows": sum(x.get("validation") == "declaration_replayed" for x in output_rows),
               "failed_rows": sum(x.get("validation") == "failed" for x in output_rows)}
    _checkpoint(output / "summary.json", summary)
    return summary
