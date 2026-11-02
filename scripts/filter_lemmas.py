#!/usr/bin/env python3
"""Inspect the lemma pre-filter used by bounded search.

This is a thin wrapper around :mod:`neuralproof.lemmas`; the extraction and
resolution logic lives in the package so the search path and offline analysis
cannot drift apart.  Filtering is a budget saver, not a validity check: a
tactic it accepts may still be rejected by Lean.

    python scripts/filter_lemmas.py "rw [List.map_smul_eq]"
    python scripts/filter_lemmas.py --index data/lemma_index.json.gz "rw [not_a_lemma]"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from neuralproof.lemmas import (  # noqa: E402
    extract_symbol_heads,
    filter_tactic as _filter_tactic,
    is_known_symbol,
    load_lemma_index,
)


def extract_lemmas_from_tactic(tactic: str) -> list[str]:
    """Backwards-compatible alias for the shared extractor."""
    return extract_symbol_heads(tactic)


def is_valid_lemma(name: str, lemma_index) -> bool:
    """Backwards-compatible alias for the shared resolver."""
    return is_known_symbol(name, lemma_index)


def filter_tactic(tactic: str, lemma_index) -> tuple[bool, str]:
    """Return ``(valid, reason)`` for one tactic, as the old script did."""
    result = _filter_tactic(tactic, lemma_index)
    if not result.symbols:
        return True, "no lemmas"
    if result.allowed:
        return True, "all valid"
    return False, "unknown lemma: " + ", ".join(result.unknown)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tactics", nargs="*", help="tactics to check")
    parser.add_argument("--index", type=Path, help="lemma index (default: data/lemma_index.json.gz)")
    parser.add_argument("--json", action="store_true", help="print machine-readable output")
    args = parser.parse_args(argv)

    index = load_lemma_index(args.index, required=args.index is not None)
    if not index:
        raise SystemExit(
            f"lemma index not found at {args.index or 'the default path'}; "
            "build it with `python scripts/build_lemma_index.py`")
    tactics = args.tactics or [
        "rw [List.map_smul_eq]",
        "rw [add_comm]",
        "simp only [List.sum]",
        "apply fun_injective",
        "rfl",
        "simp",
    ]
    rows = []
    for tactic in tactics:
        result = _filter_tactic(tactic, index)
        rows.append({"tactic": tactic, "allowed": result.allowed,
                     "symbols": list(result.symbols), "unknown": list(result.unknown)})
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(f"Loaded {len(index)} names from {args.index or 'data/lemma_index.json.gz'}")
        for row in rows:
            status = "ok" if row["allowed"] else "refuse"
            detail = ", ".join(row["unknown"]) or "no unresolved symbols"
            print(f"{status:6} {row['tactic']}  ({detail})")
    return 0 if all(row["allowed"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
