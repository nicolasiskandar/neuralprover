#!/usr/bin/env python3
"""Measure the lemma pre-filter on held-out source tactics.

Every target tactic in the held-out eval was accepted by Lean in the original
Mathlib file, so rejecting one is a false reject.  This script reports those
rejections (grouped by the unresolved name), checks how many model predictions
the filter would drop, and fails when the false-reject count exceeds a budget.

The filter is only a pre-filter; this check says nothing about proof solving.

    python scripts/check_lemma_filter.py --limit 342
    python scripts/check_lemma_filter.py --eval <eval.json> --output /tmp/report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from neuralproof.lemmas import (  # noqa: E402
    default_index_path,
    filter_tactic,
    load_lemma_index,
    symbols_in_state,
)

DEFAULT_EXAMPLES = REPO_ROOT / "data" / "mathlib-info-tree-200" / "examples.jsonl"
DEFAULT_EVAL = (REPO_ROOT / "experiments" / "mathlib-info-tree-lora-200-1epoch-canonical"
                / "tactic-eval-full-heldout.json")

# Names that do not exist in the pinned environment.  They are a sanity check
# that the filter still refuses something; a filter that accepted every name
# would pass a false-reject test vacuously.
CURATED_HALLUCINATIONS = (
    "not_a_lemma_anywhere",
    "totally_made_up_lemma_xyz",
    "fake_simp_lemma_qqq",
)


def _read_examples(path: Path) -> dict[str, dict]:
    rows = {}
    with path.open() as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("example_id"):
                rows[row["example_id"]] = row
    return rows


def _eval_targets(path: Path) -> list[dict]:
    """Target/prediction rows from an ``evaluate-tactics`` JSON artifact."""
    data = json.loads(path.read_text())
    branch = data.get("lora") or data.get("base")
    if not branch or "examples" not in branch:
        raise SystemExit(f"{path} has no lora/base examples section")
    return branch["examples"]


def check(examples: dict[str, dict], targets: list[dict], index,
          *, limit: int | None = None, include_predictions: bool = False) -> dict:
    if limit is not None:
        targets = targets[:limit]
    target_rejects = []
    prediction_rejects = []
    symbol_counts: Counter[str] = Counter()
    missing_rows = []
    for item in targets:
        row = examples.get(item["example_id"])
        if row is None:
            missing_rows.append(item["example_id"])
            continue
        allowed = symbols_in_state(row.get("context", ""), row.get("goal_state", ""),
                                   row.get("theorem", ""))
        result = filter_tactic(item["target"], index, allowed)
        if not result.allowed:
            symbol_counts.update(result.unknown)
            target_rejects.append({"example_id": item["example_id"],
                                   "tactic": item["target"],
                                   "unknown": list(result.unknown)})
        if include_predictions:
            prediction = item.get("prediction")
            if prediction:
                predicted = filter_tactic(prediction, index, allowed)
                if not predicted.allowed:
                    prediction_rejects.append({
                        "example_id": item["example_id"], "tactic": prediction,
                        "exact_match": bool(item.get("exact_match")),
                        "unknown": list(predicted.unknown)})
    correct_rejected = sum(1 for row in prediction_rejects if row["exact_match"])
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in target_rejects:
        for name in row["unknown"]:
            by_symbol[name].append(row)
    return {
        "protocol": "held-out source targets were accepted by Lean; a filter "
                    "rejection is therefore a false reject",
        "checked_targets": len(targets) - len(missing_rows),
        "missing_examples": missing_rows,
        "false_rejects": len(target_rejects),
        "false_reject_rate": (len(target_rejects) / (len(targets) - len(missing_rows))
                              if len(targets) != len(missing_rows) else 0.0),
        "false_rejects_by_symbol": {name: len(rows) for name, rows in
                                    sorted(by_symbol.items(), key=lambda item: -len(item[1]))},
        "false_reject_examples": target_rejects[:50],
        "prediction_rejects": len(prediction_rejects) if include_predictions else None,
        "correct_predictions_rejected": correct_rejected if include_predictions else None,
        "prediction_reject_examples": prediction_rejects[:50] if include_predictions else [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=Path, default=DEFAULT_EXAMPLES,
                        help="JSONL corpus with example_id, context, and goal_state")
    parser.add_argument("--eval", type=Path, default=DEFAULT_EVAL,
                        help="evaluate-tactics JSON; its targets and predictions are checked")
    parser.add_argument("--index", type=Path, default=default_index_path())
    parser.add_argument("--limit", type=int, default=342,
                        help="check only the first N held-out rows (default: 342)")
    parser.add_argument("--max-false-rejects", type=int, default=0,
                        help="exit non-zero above this many rejected source targets")
    parser.add_argument("--output", type=Path, help="write the JSON report here")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    if not args.examples.exists():
        print(f"skip: held-out corpus not found at {args.examples}; "
              "nothing to check (this is not a pass)")
        return 0
    examples = _read_examples(args.examples)
    index = load_lemma_index(args.index, required=True)

    if args.eval.exists():
        targets = _eval_targets(args.eval)
        include_predictions = True
        source = str(args.eval)
    else:
        targets = [{"example_id": example_id, "target": row.get("target_tactic", "")}
                   for example_id, row in examples.items()
                   if row.get("target_tactic")]
        include_predictions = False
        source = str(args.examples)
    report = check(examples, targets, index, limit=args.limit,
                   include_predictions=include_predictions)
    curated = {name: filter_tactic(f"rw [{name}]", index).allowed
               for name in CURATED_HALLUCINATIONS}
    report.update({"index": str(args.index), "index_size": len(index),
                   "targets_from": source,
                   "curated_hallucinations": curated,
                   "curated_accepted": [name for name, allowed in curated.items() if allowed]})

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Index: {len(index)} names ({args.index})")
        print(f"Targets: {report['checked_targets']} from {source}")
        print(f"False rejects: {report['false_rejects']} "
              f"({report['false_reject_rate']:.2%})")
        if report["missing_examples"]:
            print(f"Missing example rows: {len(report['missing_examples'])}")
        for name, count in report["false_rejects_by_symbol"].items():
            print(f"  {name}: {count}")
        for row in report["false_reject_examples"][:10]:
            print(f"  rejected: {row['tactic']}  unknown={row['unknown']}")
        if include_predictions:
            print(f"Prediction rejects: {report['prediction_rejects']} "
                  f"(correct predictions lost: {report['correct_predictions_rejected']})")
        if args.output:
            print(f"Report written to {args.output}")

    if report["false_rejects"] > args.max_false_rejects:
        print(f"FAIL: {report['false_rejects']} false rejects exceeds budget "
              f"{args.max_false_rejects}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
