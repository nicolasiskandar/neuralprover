"""Conservatively normalize Lean InfoTree snapshots into tactic examples.

InfoTrees contain nested wrapper nodes and macro-generated tactics. This module
keeps one source-backed parser tactic per span and retains the original source
text as the target. It does not claim that reconstructed contexts replay every
example; callers receive exclusion and provenance statistics for auditing.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from neuralproof.data.extraction import _active_context, _source_imports
from neuralproof.data.splits import split_for

_WRAPPERS = ("tacticSeq", "tacticSeq1Indented", "tacticSeq1", "tactic", "byTactic")


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _line_at(raw: bytes, offset: int) -> int:
    # Lean String.Pos.Raw offsets count UTF-8 bytes, not Python code points.
    return raw.count(b"\n", 0, offset)


def _source_tactic(raw: bytes, start: int, end: int) -> str:
    try:
        return raw[start:end].decode("utf-8").strip()
    except (UnicodeDecodeError, IndexError):
        return ""


def _kind_matches_source(kind: str, tactic: str) -> bool:
    keyword = re.match(r"(?:\u00b7\s*)?([A-Za-z_][\w']*)", tactic)
    if not keyword:
        return False
    leaf = kind.rsplit(".", 1)[-1].lower()
    word = keyword.group(1).lower()
    word = {"rw": "rewrite", "rwa": "rewriteall", "simp_all": "simpall"}.get(word, word)
    return leaf == word or leaf.startswith(word) or leaf.startswith("tactic" + word)


def normalize_trace(trace: dict[str, Any], source_file: str | Path, *, seed: str = "neuralproof-v1") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return source-backed one-tactic records and machine-readable exclusions."""
    path = Path(source_file)
    raw = path.read_bytes()
    source = raw.decode("utf-8")
    lines = source.splitlines()
    nodes = trace.get("traces", [])

    proof_spans: list[tuple[str, int, int]] = []
    for node in nodes:
        if node.get("syntax_kind") == "Lean.Parser.Term.byTactic" and node.get("declaration"):
            start, end = _int(node.get("source_start")), _int(node.get("source_end"))
            if start is not None and end is not None and end >= start:
                proof_spans.append((node["declaration"], start, end))

    # Resolve declaration-less Info nodes only when exactly one enclosing proof
    # span contains the full source range.
    candidates: dict[tuple[str, int, int], list[tuple[dict[str, Any], str]]] = {}
    excluded = {"missing_span": 0, "outside_proof": 0, "wrapper_or_non_tactic": 0,
                "empty_source": 0, "ambiguous_owner": 0, "invalid_range": 0}
    for node in nodes:
        start, end = _int(node.get("source_start")), _int(node.get("source_end"))
        if start is None or end is None:
            excluded["missing_span"] += 1
            continue
        if start < 0 or end < start or end > len(raw):
            excluded["invalid_range"] += 1
            continue
        kind = str(node.get("syntax_kind", ""))
        if not kind.startswith("Lean.Parser.Tactic.") or any(kind.endswith(w) for w in _WRAPPERS):
            excluded["wrapper_or_non_tactic"] += 1
            continue
        tactic = _source_tactic(raw, start, end)
        if not tactic:
            excluded["empty_source"] += 1
            continue
        owner = str(node.get("declaration", ""))
        if not owner:
            owners = {decl for decl, lo, hi in proof_spans if lo <= start and end <= hi}
            if len(owners) != 1:
                excluded["ambiguous_owner" if owners else "outside_proof"] += 1
                continue
            owner = next(iter(owners))
        if "\n" in tactic:
            # InfoTree spans for one tactic normally stay on one line. A span
            # that crosses lines may bundle several commands, so exclude it.
            excluded["wrapper_or_non_tactic"] += 1
            continue
        candidates.setdefault((owner, start, end), []).append((node, tactic))

    rows: list[dict[str, Any]] = []
    duplicate_spans = 0
    for index, ((owner, start, end), group) in enumerate(sorted(candidates.items(), key=lambda item: (item[0][1], item[0][2], item[0][0]))):
        if len(group) > 1:
            duplicate_spans += len(group) - 1
        node, tactic = sorted(group, key=lambda pair: (not _kind_matches_source(str(pair[0].get("syntax_kind", "")), pair[1]), str(pair[0].get("syntax_kind", ""))))[0]
        line_index = _line_at(raw, start)
        context = _active_context(lines, line_index, _source_imports(lines, line_index))
        safe_source = re.sub(r"[^A-Za-z0-9_]", "_", str(trace.get("source_file", path.name)))
        safe_decl = re.sub(r"[^A-Za-z0-9_]", "_", owner)
        rows.append({
            "example_id": f"{safe_source}::{safe_decl}::{start}-{end}",
            "theorem_id": f"{safe_source}::{owner}",
            "source_declaration": owner,
            "context": context,
            "goal_state": node.get("goal_state", ""),
            "target_tactic": tactic,
            "result_state": node.get("result_state", ""),
            "completed_after_tactic": bool(node.get("completed", False)),
            "source_file": trace.get("source_file", str(path)),
            "split": split_for(str(trace.get("source_file", path)), seed),
            "source_revision": trace.get("source_revision"),
            "source_start": start,
            "source_end": end,
            "proof_start": next((lo for decl, lo, _ in proof_spans
                                 if decl == owner and lo <= start <= end), None),
            "source_line": line_index + 1,
            "syntax_kind": node.get("syntax_kind", ""),
            "validation": "original_file_elaborated; transition_replay_pending",
        })

    stats = {
        "source_file": trace.get("source_file", str(path)),
        "source_revision": trace.get("source_revision"),
        "input_nodes": len(nodes),
        "output_examples": len(rows),
        "deduplicated_nodes": duplicate_spans,
        "excluded": excluded,
        "context_policy": "source_imports_and_active_context_excluding_target",
        "validation_policy": "original_file_elaborated; standalone replay not claimed",
    }
    return rows, stats


def replay_transition(trace: dict[str, Any], source_file: str | Path,
                      row: dict[str, Any], *, project_dir: str | Path | None = None,
                      timeout: float = 120) -> dict[str, Any]:
    """Compile the original module prefix and one selected tactic transition.

    Remaining goals are closed with `sorry` solely to let Lean finish elaborating
    the harness. A successful result validates tactic execution in context; it
    is never a verified theorem or proof result.
    """
    project = Path(project_dir or Path(__file__).parents[2] / "lean").resolve()
    path = Path(source_file)
    raw = path.read_bytes()
    start, end = _int(row.get("source_start")), _int(row.get("source_end"))
    if start is None or end is None or start < 0 or end <= start or end > len(raw):
        return {"status": "rejected", "reason": "invalid_tactic_span"}
    owner = row.get("source_declaration")
    proof = next((n for n in trace.get("traces", [])
                  if n.get("syntax_kind") == "Lean.Parser.Term.byTactic"
                  and n.get("declaration") == owner
                  and _int(n.get("source_start")) is not None
                  and _int(n.get("source_end")) is not None
                  and int(n["source_start"]) <= start <= int(n["source_end"])), None)
    if proof is None:
        return {"status": "rejected", "reason": "proof_span_not_found"}
    proof_start, proof_end = int(proof["source_start"]), int(proof["source_end"])
    body = next((n for n in trace.get("traces", [])
                 if n.get("syntax_kind") == "by" and n.get("declaration") == owner
                 and _int(n.get("source_start")) == proof_start
                 and _int(n.get("source_end")) is not None), None)
    if body is None:
        return {"status": "rejected", "reason": "proof_body_boundary_not_found"}
    body_end = int(body["source_end"])
    commands = [n for n in trace.get("commands", [])
                if n.get("syntax_kind") == "Lean.Parser.Command.declaration"
                and _int(n.get("source_start")) is not None
                and _int(n.get("source_end")) is not None
                and int(n["source_start"]) <= proof_start
                and int(n["source_end"]) >= proof_end]
    if not commands:
        return {"status": "rejected", "reason": "declaration_command_not_found"}
    command = min(commands, key=lambda n: int(n["source_end"]) - int(n["source_start"]))
    command_start = int(command["source_start"])
    # Prefix all prior commands/imports so local declarations and scoped syntax
    # remain available. Keep the theorem header and original preceding tactics.
    indent = raw[raw.rfind(b"\n", 0, start) + 1:start]
    indent = indent[:len(indent) - len(indent.lstrip(b" \t"))]
    harness = (raw[:body_end] + raw[body_end:start] + raw[start:end]
               + b"\n" + indent + b"all_goals sorry\n")
    try:
        with tempfile.NamedTemporaryFile(suffix=".lean", dir=project, delete=False) as tmp:
            tmp.write(harness)
            temp_path = Path(tmp.name)
        proc = subprocess.run(["lake", "env", "lean", str(temp_path)], cwd=project,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "lean_transition_timeout"}
    except OSError as exc:
        return {"status": "error", "reason": str(exc)}
    finally:
        if "temp_path" in locals():
            temp_path.unlink(missing_ok=True)
    if proc.returncode:
        # Some tactic transitions sit inside syntax that requires a complete
        # set of branches (for example `induction ... with`). In that case a
        # standalone partial proof is not syntactically representable. Replay
        # the complete source declaration, preserving all branches and its
        # original environment, rather than silently dropping the example.
        command_end = int(command["source_end"])
        complete = raw[:command_start] + raw[command_start:command_end]
        try:
            with tempfile.NamedTemporaryFile(suffix=".lean", dir=project, delete=False) as tmp:
                tmp.write(complete)
                full_path = Path(tmp.name)
            full_proc = subprocess.run(["lake", "env", "lean", str(full_path)], cwd=project,
                                       capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "reason": "full_declaration_replay_timeout"}
        finally:
            if "full_path" in locals():
                full_path.unlink(missing_ok=True)
        if full_proc.returncode:
            return {"status": "failed", "reason": "lean_rejected_transition_and_declaration",
                    "diagnostic": (proc.stdout + proc.stderr + full_proc.stdout + full_proc.stderr)[-4000:]}
        return {"status": "declaration_replayed", "reason": "partial_harness_not_representable",
                "harness_contains_sorry": False, "proof_start": proof_start,
                "declaration_start": command_start}
    return {"status": "replayed", "reason": None, "harness_contains_sorry": True,
            "proof_start": proof_start, "declaration_start": command_start}


def validate_trace_examples(trace: dict[str, Any], source_file: str | Path,
                            rows: list[dict[str, Any]], *,
                            project_dir: str | Path | None = None,
                            timeout: float = 120) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replay the latest source tactic in each declaration and annotate rows.

    A successful prefix replay checks every preceding tactic in that proof. If
    Lean's syntax requires the remaining branches, the validator compiles the
    complete original declaration instead. One check is shared by all rows in
    that declaration to keep file-level validation practical.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["source_declaration"], []).append(row)
    results: dict[str, dict[str, Any]] = {}
    for decl, items in grouped.items():
        last = max(items, key=lambda row: (int(row["source_end"]), int(row["source_start"])))
        results[decl] = replay_transition(trace, source_file, last,
                                          project_dir=project_dir, timeout=timeout)
    annotated = []
    for row in rows:
        result = results[row["source_declaration"]]
        annotated.append({**row, "validation": result["status"],
                          "validation_reason": result.get("reason"),
                          "validation_harness_contains_sorry": result.get("harness_contains_sorry", False)})
    stats = {"source_file": trace.get("source_file", str(source_file)),
             "rows": len(rows), "declarations_count": len(grouped),
             "validation_counts": {status: sum(x["status"] == status for x in results.values())
                                   for status in sorted({x["status"] for x in results.values()})},
             "declaration_results": {name: result for name, result in sorted(results.items())},
             "policy": "latest_tactic_prefix_per_declaration; complete_declaration_fallback"}
    return annotated, stats


def normalize_trace_file(trace_file: str | Path, source_file: str | Path,
                         output_file: str | Path) -> dict[str, Any]:
    trace = json.loads(Path(trace_file).read_text())
    rows, stats = normalize_trace(trace, source_file)
    output = Path(output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    stats_path = output.with_suffix(output.suffix + ".stats.json")
    stats_path.write_text(json.dumps(stats, indent=2) + "\n")
    return stats
