"""Kernel-checked tactic acceptance on held-out next-tactic rows.

This module joins the existing held-out predictions to their source positions,
self-checks the original transition, substitutes each model prediction into the
same position, and asks Lean to classify the result.  It never regenerates a
prediction and never changes a prompt or a checkpoint, so an acceptance number
describes the already-trained models rather than a new system.

The statuses are deliberately narrow:

``closed``
    Lean exits successfully; the replacement left no goals.
``accepted``
    Lean's only error is that goals remain (the tactic applied).
``rejected``
    Lean reported any other error (parse error, unknown tactic, failed side
    condition, or a placeholder token).
``empty``
    The model produced no output for the row.
``timeout``
    The Lean run exceeded the per-run timeout.
``unsupported``
    The original source target did not self-check, so the row cannot be used
    as an acceptance test.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from neuralproof.data.preprocessing import is_tactic_target
from neuralproof.lean.transition import (
    Harness,
    HarnessRun,
    TraceCache,
    TransitionError,
    build_harness,
    classify_output,
    find_transition_span,
    run_harness,
)

STATUSES = ("closed", "accepted", "rejected", "empty", "timeout", "unsupported")
_ACCEPTED = frozenset({"closed", "accepted"})
_PLACEHOLDER = re.compile(r"\b(?:sorry|admit)\b")

_IDENTIFIER = re.compile(r"[^\W\d][\w']*(?:\.[^\W\d][\w']*)*")
_TACTIC_HEADS = frozenset("""
simp simp_all simp_rw rw rewrite erw simpa dsimp apply exact refine refine' eapply
have obtain intro intros ext ext1 rcases induction cases rfl let letI change
assumption infer_instance lift by_cases by_contra use subst congr conv conv_lhs
conv_rhs replace abel grind congrm funext unfold set specialize generalize clear
rename revert constructor left right exists decide native_decide norm_num
linarith nlinarith omega positivity ring ring_nf field_simp push_cast
""".split())


def wilson_interval(successes: int, total: int) -> list[float] | None:
    if total <= 0:
        return None
    z = 1.96
    rate = successes / total
    denominator = 1 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    half = z * math.sqrt(rate * (1 - rate) / total
                         + z * z / (4 * total * total)) / denominator
    return [max(0.0, centre - half), min(1.0, centre + half)]


def tactic_family(target: str, syntax_kind: str) -> str:
    """The same family labels used by the retrieval report."""
    head = target.strip().split(maxsplit=1)[0] if target.strip() else "<empty>"
    if head in _TACTIC_HEADS:
        return head
    if head and _IDENTIFIER.fullmatch(head):
        kind = syntax_kind.rsplit(".", 1)[-1] if syntax_kind else ""
        return {
            "rewriteSeq": "rw",
            "allGoals": "all_goals",
            "tacticRfl": "rfl",
            "tacticInfer_instance": "infer_instance",
            "applyRfl": "apply_rfl",
        }.get(kind, kind.lower() or head)
    return head


def read_examples(path: str | Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with Path(path).open() as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("example_id"):
                rows[row["example_id"]] = row
    return rows


def load_predictions(path: str | Path, models: Iterable[str]) -> tuple[
        dict[str, Any], dict[str, dict[str, dict[str, Any]]]]:
    payload = json.loads(Path(path).read_text())
    if "examples" in payload and isinstance(payload.get("examples"), list):
        payload = {"model": payload}
    selected = list(models)
    by_model: dict[str, dict[str, dict[str, Any]]] = {}
    for model in selected:
        branch = payload.get(model)
        if not isinstance(branch, dict) or "examples" not in branch:
            raise ValueError(f"{path} has no {model!r} examples section")
        by_model[model] = {
            str(item["example_id"]): item for item in branch["examples"]
            if item.get("example_id")
        }
    return payload, by_model


def select_rows(examples_path: str | Path, eval_path: str | Path,
                models: Iterable[str]) -> list[dict[str, Any]]:
    """Join the exact held-out eval ids to their corpus rows and predictions."""
    models = list(models)
    examples = read_examples(examples_path)
    _, predictions = load_predictions(eval_path, models)
    reference = predictions[models[0]]
    missing_from_models = [
        model for model in models[1:] if set(predictions[model]) != set(reference)
    ]
    if missing_from_models:
        raise ValueError(
            "eval sections do not contain the same example ids: "
            + ", ".join(missing_from_models))

    rows: list[dict[str, Any]] = []
    for example_id, eval_item in reference.items():
        row = examples.get(example_id)
        if row is None:
            raise ValueError(f"missing corpus row {example_id}")
        if not is_tactic_target(row.get("target_tactic", "")):
            raise ValueError(f"{example_id} has a non-tactic target")
        item: dict[str, Any] = {
            "example_id": example_id,
            "row": row,
            "predictions": {},
            "exact_match": {},
            "produced_output": {},
        }
        for model in models:
            predicted = predictions[model][example_id]
            prediction = str(predicted.get("prediction", "") or "").strip()
            item["predictions"][model] = prediction
            item["exact_match"][model] = bool(predicted.get(
                "exact_match", prediction == row.get("target_tactic", "").strip()))
            item["produced_output"][model] = bool(predicted.get(
                "produced_output", bool(prediction)))
        rows.append(item)
    return rows


def sample_rows(rows: list[dict[str, Any]], limit: int,
                sample_by: str = "none") -> list[dict[str, Any]]:
    """Deterministically stratify a pilot sample without touching the targets."""
    if limit <= 0 or limit >= len(rows):
        return list(rows)
    if sample_by == "none":
        return list(rows[:limit])
    if sample_by not in {"family", "file"}:
        raise ValueError(f"unknown sample mode {sample_by!r}")
    key = (lambda row: tactic_family(row["row"].get("target_tactic", ""),
                                     row["row"].get("syntax_kind", ""))
           if sample_by == "family" else row["row"].get("source_file", ""))
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    ordered = [groups[name] for name in sorted(groups)]
    selected: list[dict[str, Any]] = []
    depth = 0
    while len(selected) < limit:
        added = False
        for group in ordered:
            if depth < len(group) and len(selected) < limit:
                selected.append(group[depth])
                added = True
        if not added:
            break
        depth += 1
    return selected


def _record_base(row: dict[str, Any], span: Any = None) -> dict[str, Any]:
    syntax_kind = str(row.get("syntax_kind", ""))
    target = str(row.get("target_tactic", ""))
    return {
        "example_id": row.get("example_id", ""),
        "source_file": row.get("source_file", ""),
        "source_declaration": row.get("source_declaration", ""),
        "source_line": row.get("source_line"),
        "syntax_kind": syntax_kind,
        "target": target,
        "family": tactic_family(target, syntax_kind),
        "goal_scope": row.get("goal_scope", "proof"),
        **({"transition": span.as_dict()} if span is not None else {}),
    }


def process_row(item: dict[str, Any], trace: dict[str, Any],
                source_path: str | Path, *, models: Iterable[str],
                project_dir: str | Path | None = None,
                timeout: float = 120) -> dict[str, Any]:
    """Self-check one row and run every model prediction against it."""
    models = list(models)
    row = item["row"]
    record = _record_base(row)
    record["orig_exact_match"] = {
        model: bool(item["exact_match"].get(model)) for model in models}
    record["models"] = {}

    try:
        self_harness = build_harness(trace, source_path, row, None,
                                     project_dir=project_dir,
                                     close_remaining=True)
    except (TransitionError, OSError, ValueError) as error:
        record["transition"] = {
            "target_kind": "unknown", "is_fragment": None,
            "reason": f"build_failed: {error}"}
        record["self_check"] = {
            "status": "unsupported", "reason": f"build_failed: {error}",
            "elapsed_seconds": 0.0}
        for model in models:
            record["models"][model] = {
                "prediction": item["predictions"][model],
                "produced_output": bool(item["predictions"][model]),
                "exact_match": bool(item["exact_match"].get(model)),
                "status": "unsupported",
                "reason": "self_check_build_failed",
                "elapsed_seconds": 0.0,
            }
        return record

    record["transition"] = self_harness.span.as_dict()
    self_run = run_harness(self_harness.text, project_dir=project_dir,
                           timeout=timeout)
    self_class = classify_output(self_run)
    self_strategy = "close_remaining"
    if self_class.status == "rejected":
        # The closing tactic can itself be unrepresentable for a layout the
        # harness cannot continue (for example a proof whose first tactic is
        # inline).  Retry without it: a target that applies but leaves goals
        # is ``accepted`` and still proves the row is representable.
        try:
            fallback = build_harness(trace, source_path, row, None,
                                     project_dir=project_dir,
                                     close_remaining=False)
            fallback_run = run_harness(fallback.text, project_dir=project_dir,
                                       timeout=timeout)
            fallback_class = classify_output(fallback_run)
        except (TransitionError, OSError, RuntimeError, ValueError):
            fallback_class = None
        if fallback_class is not None and fallback_class.status in _ACCEPTED:
            self_harness = fallback
            self_run = fallback_run
            self_class = fallback_class
            self_strategy = "no_close"
    record["self_check"] = {
        "status": self_class.status,
        "reason": self_class.reason,
        "strategy": self_strategy,
        "elapsed_seconds": self_run.elapsed_seconds,
        "diagnostic": self_class.diagnostic,
    }

    if self_class.status not in _ACCEPTED:
        for model in models:
            record["models"][model] = {
                "prediction": item["predictions"][model],
                "produced_output": bool(item["predictions"][model]),
                "exact_match": bool(item["exact_match"].get(model)),
                "status": "unsupported",
                "reason": f"self_check_{self_class.status}",
                "elapsed_seconds": 0.0,
            }
        return record

    for model in models:
        prediction = item["predictions"][model]
        entry: dict[str, Any] = {
            "prediction": prediction,
            "produced_output": bool(prediction),
            "exact_match": bool(item["exact_match"].get(model)),
            "status": "empty",
            "reason": "no_prediction",
            "elapsed_seconds": 0.0,
        }
        if not prediction:
            record["models"][model] = entry
            continue
        if _PLACEHOLDER.search(prediction):
            entry["status"] = "rejected"
            entry["reason"] = "placeholder_token"
            record["models"][model] = entry
            continue
        try:
            harness = build_harness(trace, source_path, row, prediction,
                                    project_dir=project_dir,
                                    close_remaining=False)
            outcome = run_harness(harness.text, project_dir=project_dir,
                                  timeout=timeout)
            classification = classify_output(outcome)
        except (TransitionError, OSError, RuntimeError, ValueError) as error:
            entry["status"] = "rejected"
            entry["reason"] = f"candidate_harness_failed: {error}"
            record["models"][model] = entry
            continue
        entry.update({
            "status": classification.status,
            "reason": classification.reason,
            "elapsed_seconds": outcome.elapsed_seconds,
            "diagnostic": classification.diagnostic,
        })
        record["models"][model] = entry
    return record


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _summarize(records: list[dict[str, Any]], model: str) -> dict[str, Any]:
    statuses = [record["models"][model]["status"] for record in records]
    counts = Counter(statuses)
    closed = counts.get("closed", 0)
    accepted = counts.get("accepted", 0)
    accepted_or_closed = closed + accepted
    unsupported = counts.get("unsupported", 0)
    empty = counts.get("empty", 0)
    supported = len(records) - unsupported
    evaluable = supported - empty
    exact = sum(bool(record["models"][model].get("exact_match"))
                for record in records)
    elapsed = [record["models"][model].get("elapsed_seconds", 0.0)
               for record in records
               if record["models"][model]["status"] in _ACCEPTED
               or record["models"][model]["status"] in {"rejected", "timeout"}]
    return {
        "rows": len(records),
        "status_counts": {status: counts.get(status, 0) for status in STATUSES},
        "supported_rows": supported,
        "evaluable_rows": evaluable,
        "closed": closed,
        "accepted": accepted,
        "accepted_or_closed": accepted_or_closed,
        "closed_rate_supported": _rate(closed, supported),
        "acceptance_rate_supported": _rate(accepted_or_closed, supported),
        "acceptance_rate_evaluated": _rate(accepted_or_closed, evaluable),
        "acceptance_rate_total": _rate(accepted_or_closed, len(records)),
        "acceptance_wilson95": wilson_interval(accepted_or_closed, supported),
        "exact_matches": exact,
        "exact_match_rate": _rate(exact, len(records)),
        "exact_and_accepted": sum(
            bool(record["models"][model].get("exact_match"))
            and record["models"][model]["status"] in _ACCEPTED
            for record in records),
        "mean_lean_seconds": (statistics.mean(elapsed) if elapsed else None),
        "median_lean_seconds": (statistics.median(elapsed) if elapsed else None),
    }


def _grouped(records: list[dict[str, Any]], models: list[str],
             key) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(key(record))].append(record)
    return {
        name: {model: _summarize(rows, model) for model in models}
        for name, rows in sorted(groups.items())
    }


def _crosstab(records: list[dict[str, Any]], model: str) -> dict[str, Any]:
    table = {status: {"exact": 0, "not_exact": 0} for status in STATUSES}
    for record in records:
        exact = "exact" if record["models"][model].get("exact_match") else "not_exact"
        table[record["models"][model]["status"]][exact] += 1
    return table


def _paired(records: list[dict[str, Any]], base: str,
            lora: str) -> dict[str, Any]:
    transitions = Counter()
    both_ok = base_only = lora_only = neither = 0
    both_closed = base_closed_only = lora_closed_only = 0
    exact = Counter()
    for record in records:
        base_status = record["models"][base]["status"]
        lora_status = record["models"][lora]["status"]
        transitions[f"{base_status}->{lora_status}"] += 1
        base_ok = base_status in _ACCEPTED
        lora_ok = lora_status in _ACCEPTED
        if base_ok and lora_ok:
            both_ok += 1
        elif base_ok:
            base_only += 1
        elif lora_ok:
            lora_only += 1
        else:
            neither += 1
        if base_status == "closed" and lora_status == "closed":
            both_closed += 1
        elif base_status == "closed":
            base_closed_only += 1
        elif lora_status == "closed":
            lora_closed_only += 1
        base_exact = bool(record["models"][base].get("exact_match"))
        lora_exact = bool(record["models"][lora].get("exact_match"))
        if base_exact and lora_exact:
            exact["both"] += 1
        elif base_exact:
            exact["base_only"] += 1
        elif lora_exact:
            exact["lora_only"] += 1
        else:
            exact["neither"] += 1
    return {
        "base": base,
        "lora": lora,
        "rows": len(records),
        "both_accepted_or_closed": both_ok,
        "base_only": base_only,
        "lora_only": lora_only,
        "neither": neither,
        "both_closed": both_closed,
        "base_closed_only": base_closed_only,
        "lora_closed_only": lora_closed_only,
        "status_transitions": dict(sorted(transitions.items())),
        "exact_match": {name: exact.get(name, 0)
                        for name in ("both", "base_only", "lora_only", "neither")},
    }


def aggregate(records: list[dict[str, Any]], models: Iterable[str]) -> dict[str, Any]:
    models = list(models)
    payload: dict[str, Any] = {
        "rows": len(records),
        "models": {model: _summarize(records, model) for model in models},
        "self_check": dict(sorted(Counter(
            record["self_check"]["status"] for record in records).items())),
        "by_family": _grouped(records, models,
                              lambda record: record["family"]),
        "by_file": _grouped(records, models,
                            lambda record: record["source_file"]),
        "by_target_kind": _grouped(records, models,
                                   lambda record: record.get("transition", {}).get(
                                       "target_kind", "unknown")),
        "exact_crosstab": {model: _crosstab(records, model) for model in models},
    }
    if len(models) >= 2:
        payload["paired"] = _paired(records, models[0], models[1])
    return payload


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |",
             "| " + " | ".join(":--" for _ in header) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def markdown_report(payload: dict[str, Any]) -> str:
    protocol = payload.get("protocol", {})
    models = list(payload.get("models", {}))
    lines = [
        "# Kernel-checked tactic acceptance",
        "",
        "Lean checks each held-out model prediction at the source target's own",
        "position. A fragment target is substituted into its enclosing tactic.",
        "Remaining goals are closed with `sorry`; this is a diagnostic of",
        "tactic acceptance, not a proof-solving result.",
        "",
        "## Protocol",
        "",
        f"- Rows: {payload.get('rows', 0)}",
        f"- Models: {', '.join(f'`{model}`' for model in models) or 'none'}",
        f"- Timeout per Lean run: {protocol.get('timeout_seconds')} seconds",
        f"- Workers: {protocol.get('workers')}",
        f"- Trace cache: `{protocol.get('trace_cache')}`",
        f"- Source revision: `{protocol.get('source_revision')}`",
        f"- Lean toolchain: `{protocol.get('lean_toolchain')}`",
        "",
        "## Acceptance",
        "",
    ]
    header = ["model", "rows", "supported", "closed", "accepted", "rejected",
              "empty", "timeout", "unsupported", "accepted+closed",
              "rate (supported)"]
    rows = []
    for model in models:
        summary = payload["models"][model]
        counts = summary["status_counts"]
        rows.append([
            f"`{model}`", str(summary["rows"]), str(summary["supported_rows"]),
            str(counts["closed"]), str(counts["accepted"]),
            str(counts["rejected"]), str(counts["empty"]),
            str(counts["timeout"]), str(counts["unsupported"]),
            str(summary["accepted_or_closed"]),
            _percent(summary["acceptance_rate_supported"]),
        ])
    lines.extend(_table(header, rows))
    lines += ["", "### Exact-match crosstab", ""]
    for model in models:
        lines.append(f"`{model}`:")
        rows = []
        for status in STATUSES:
            entry = payload["exact_crosstab"][model][status]
            rows.append([status, str(entry["exact"]), str(entry["not_exact"])])
        lines.extend(_table(["status", "exact", "not exact"], rows))
        lines.append("")

    lines += ["## By target kind", ""]
    for kind, by_model in payload.get("by_target_kind", {}).items():
        lines.append(f"### `{kind}`")
        rows = []
        for model in models:
            summary = by_model[model]
            rows.append([f"`{model}`", str(summary["rows"]),
                         str(summary["accepted_or_closed"]),
                         str(summary["supported_rows"]),
                         _percent(summary["acceptance_rate_supported"])])
        lines.extend(_table(
            ["model", "rows", "accepted+closed", "supported", "rate"], rows))
        lines.append("")

    if "paired" in payload:
        paired = payload["paired"]
        lines += [
            "## Paired comparison", "",
            f"- Both accepted or closed: {paired['both_accepted_or_closed']}",
            f"- `{paired['base']}` only: {paired['base_only']}",
            f"- `{paired['lora']}` only: {paired['lora_only']}",
            f"- Neither: {paired['neither']}",
            f"- Both closed: {paired['both_closed']}",
            f"- `{paired['base']}` closed only: {paired['base_closed_only']}",
            f"- `{paired['lora']}` closed only: {paired['lora_closed_only']}",
            "",
            "### Status transitions",
            "",
        ]
        lines.extend(_table(
            ["transition", "rows"],
            [[transition, str(count)]
             for transition, count in paired["status_transitions"].items()]))
        lines.append("")

    lines += ["## Notes", "",
              "- `unsupported` means the original source target did not self-check;",
              "  those rows are excluded from the supported denominator.",
              "- `accepted` requires Lean's only error to be `unsolved goals`.",
              "  A parse error or a failed side condition is `rejected`.",
              "- Placeholder predictions (`sorry`/`admit`) are rejected without a",
              "  Lean run, so they cannot appear as accepted.",
              "- Exact match is the existing greedy string metric; acceptance is a",
              "  separate, weaker diagnostic. Neither is proof-solving performance.",
              ""]
    return "\n".join(lines)


def write_report(output_dir: str | Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report_json = output / "report.json"
    report_md = output / "report.md"
    report_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    report_md.write_text(markdown_report(payload) + "\n")
    return report_json, report_md
