"""Held-out greedy exact-match evaluation for next-tactic prediction."""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

from neuralproof.lean.client import ProofState


def _wilson(correct: int, total: int) -> list[float] | None:
    if total == 0:
        return None
    z = 1.96
    rate = correct / total
    denom = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denom
    half = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denom
    return [max(0.0, center - half), min(1.0, center + half)]


def _metric(model: str, predictor: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter()
    details = []
    for row in rows:
        state = ProofState(theorem=row.get("theorem", ""), context=row["context"],
                           goals=(row["goal_state"],))
        candidates = predictor.predict(state, 1)
        prediction = candidates[0].tactic.strip() if candidates else ""
        target = row["target_tactic"].strip()
        details.append({"example_id": row.get("example_id", row.get("theorem_id", "")),
                        "source_file": row["source_file"], "target": target,
                        "prediction": prediction, "exact_match": prediction == target})
    elapsed = time.perf_counter() - started
    correct = sum(item["exact_match"] for item in details)
    total = len(details)
    return {"model": model, "attempted": total, "exact_matches": correct,
            "exact_match_accuracy": correct / total if total else None,
            "wilson95": _wilson(correct, total), "inference_seconds": elapsed,
            "examples": details}


def evaluate_tactic_prediction(data: str | Path, output: str | Path, *,
                               base_model: str, revision: str | None,
                               adapter: str, limit: int = 100,
                               seed: str = "neuralproof-next-tactic-v1") -> dict[str, Any]:
    """Compare base and LoRA greedy top-1 on the same held-out single-line targets."""
    if limit < 1:
        raise ValueError("limit must be positive")
    all_rows = [json.loads(line) for line in Path(data).read_text().splitlines() if line.strip()]
    heldout = [row for row in all_rows if row.get("split") == "test"]
    eligible = [row for row in heldout if "\n" not in row.get("target_tactic", "").strip()]
    selected = sorted(eligible, key=lambda row: hashlib.sha256(
        (seed + row.get("example_id", row.get("theorem_id", ""))).encode()).hexdigest())[:limit]
    if not selected:
        raise ValueError("no held-out single-line tactic examples found")

    from neuralproof.models.predictor import load_hf_predictor
    base = load_hf_predictor(base_model, revision=revision)
    tuned = load_hf_predictor(base_model, adapter=adapter, revision=revision)
    results = {
        "protocol": "greedy top-1; strip outer whitespace; exact string match; single-line source targets only",
        "data_file": str(data), "heldout_examples": len(heldout),
        "eligible_single_line_examples": len(eligible), "sample_size": len(selected),
        "seed": seed, "base_model": base_model, "model_revision": revision,
        "adapter": str(adapter),
        "base": _metric("base", base, selected),
        "lora": _metric("lora", tuned, selected),
    }
    dest = Path(output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    return results
