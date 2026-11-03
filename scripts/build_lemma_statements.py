#!/usr/bin/env python3
"""Build a lemma-statement corpus from a Lean declaration dump.

The Lean side (``NeuralProof/DumpStatements.lean``) prints one JSON object per
line with ``name``, ``kind`` and ``type``.  This script validates and sorts
those records, optionally joins the module that defined each declaration
(``NeuralProof/DumpModules.lean``), drops private/compiler-generated names, and
writes a deterministic gzip JSONL corpus plus a provenance file.

The corpus is retrieval input, not a proof artifact: a pretty-printed type is
not re-elaborated, and a retrieval hit is not a verified lemma application.

    python scripts/build_lemma_statements.py \
        --from-file /tmp/mathlib-statements.jsonl \
        --modules-file /tmp/mathlib-modules.tsv

    python scripts/build_lemma_statements.py --output data/lemma_statements.jsonl.gz
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from neuralproof.data.provenance import (  # noqa: E402
    code_diff_sha256,
    code_revision,
    sha256_file,
    sha256_text,
    working_tree_state,
)

# Names that the source language cannot reference: private declarations and
# compiler-generated auxiliaries (equation/match/proof helpers, recursors,
# no-confusion lemmas).  Keeping them would inflate the candidate set with
# entries no held-out tactic can name.
_INTERNAL_NAME = re.compile(
    r"(?:^|\.)_private\.|\._@|\._proof_|\.match_|\.noConfusion|"
    r"\.recOn(?:_|\.|$)|\.casesOn(?:_|\.|$)|\.brecOn(?:_|\.|$)|"
    r"\.below(?:_|\.|$)|\._flat_ctor(?:_|\.|$)|\.ctorIdx(?:_|\.|$)"
)

# Equation lemmas are generated for every definition; they are occasionally
# usable by ``simp`` but are rarely written in source tactics.  They remain in
# the corpus unless ``--drop-equation-lemmas`` is passed.
_EQUATION_LEMMA = re.compile(r"\.eq(?:_\d+)?$")

_FIELD_ORDER = ("name", "kind", "type", "module")


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _mathlib_revision(lean_root: Path) -> str | None:
    manifest = lean_root / "lake-manifest.json"
    if not manifest.exists():
        return None
    for package in json.loads(manifest.read_text()).get("packages", []):
        if package.get("name") == "mathlib":
            return package.get("rev")
    return None


def _toolchain(lean_root: Path) -> str | None:
    toolchain = lean_root / "lean-toolchain"
    return toolchain.read_text().strip() if toolchain.exists() else None


def _run_lean(lean_root: Path, command: list[str], timeout: float) -> str:
    completed = subprocess.run(command, cwd=lean_root, capture_output=True,
                               text=True, timeout=timeout)
    if completed.returncode != 0:
        raise SystemExit(
            f"Lean command {' '.join(command)} failed with exit status "
            f"{completed.returncode}:\n{completed.stderr.strip()}")
    return completed.stdout


def read_statement_dump(text: str) -> list[dict[str, str]]:
    """Parse and validate the JSONL written by ``DumpStatements.lean``."""
    records: list[dict[str, str]] = []
    seen: dict[str, dict[str, str]] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"line {line_number} is not JSON: {error}") from error
        if not isinstance(raw, dict):
            raise ValueError(f"line {line_number} is not a JSON object")
        name = raw.get("name")
        kind = raw.get("kind")
        statement = raw.get("type")
        if not isinstance(name, str) or not name:
            raise ValueError(f"line {line_number} has no non-empty name")
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"line {line_number} has no non-empty kind")
        if not isinstance(statement, str):
            raise ValueError(f"line {line_number} has no string type")
        record = {"name": name, "kind": kind, "type": statement}
        previous = seen.get(name)
        if previous is not None:
            if previous != record:
                raise ValueError(f"conflicting duplicate declaration {name}")
            continue
        seen[name] = record
        records.append(record)
    return records


def read_module_map(path: Path) -> dict[str, str]:
    """Read ``module<TAB>name`` lines from ``DumpModules.lean``."""
    return read_module_map_text(path.read_text())


def read_module_map_text(text: str) -> dict[str, str]:
    """Parse the ``module<TAB>name`` map."""
    modules: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if "\t" not in line:
            raise ValueError(f"module map line {line_number} has no tab separator")
        module, name = line.split("\t", 1)
        if not module or not name:
            raise ValueError(f"module map line {line_number} is incomplete")
        modules[name] = module
    return modules


def is_internal_name(name: str) -> bool:
    return bool(_INTERNAL_NAME.search(name))


def prepare_statements(records: Iterable[dict[str, str]],
                       modules: dict[str, str] | None = None, *,
                       drop_internal: bool = True,
                       drop_equation_lemmas: bool = False,
                       kinds: set[str] | None = None) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Normalize, join modules, filter and sort declarations for retrieval."""
    prepared: list[dict[str, str]] = []
    counts: Counter[str] = Counter()
    dropped: Counter[str] = Counter()
    missing_modules = 0
    for record in records:
        kind = record["kind"]
        counts[kind] += 1
        if kinds is not None and kind not in kinds:
            dropped["kind"] += 1
            continue
        if drop_internal and is_internal_name(record["name"]):
            dropped["internal"] += 1
            continue
        if drop_equation_lemmas and _EQUATION_LEMMA.search(record["name"]):
            dropped["equation_lemma"] += 1
            continue
        item = dict(record)
        if modules is not None:
            module = modules.get(record["name"])
            if module is None:
                missing_modules += 1
            else:
                item["module"] = module
        prepared.append(item)
    prepared.sort(key=lambda item: item["name"])
    summary = {
        "input_kinds": dict(sorted(counts.items())),
        "input_count": sum(counts.values()),
        "output_count": len(prepared),
        "dropped": dict(sorted(dropped.items())),
        "missing_modules": missing_modules,
    }
    return prepared, summary


def write_corpus(path: Path, records: Iterable[dict[str, str]]) -> None:
    """Write deterministic gzip JSONL (fixed mtime, sorted records)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps({field: record[field] for field in _FIELD_ORDER if field in record},
                   ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in records
    ).encode("utf-8")
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(payload, 9, mtime=0))
    else:
        path.write_bytes(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lean-root", type=Path, default=REPO_ROOT / "lean")
    parser.add_argument("--from-file", type=Path,
                        help="read a captured statement dump instead of running Lean")
    parser.add_argument("--modules-file", type=Path,
                        help="module<TAB>constant map used to record provenance")
    parser.add_argument("--statement-dumper", default="NeuralProof/DumpStatements.lean")
    parser.add_argument("--module-dumper", default="NeuralProof/DumpModules.lean")
    parser.add_argument("--import-module", default="Mathlib")
    parser.add_argument("--kinds", default="theorem,def,constructor",
                        help="comma-separated declaration kinds to keep")
    parser.add_argument("--drop-equation-lemmas", action="store_true",
                        help="also drop generated .eq/.eq_N lemmas")
    parser.add_argument("--keep-internal", action="store_true",
                        help="keep private and compiler-generated names")
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "data" / "lemma_statements.jsonl.gz")
    parser.add_argument("--meta", type=Path,
                        default=REPO_ROOT / "data" / "lemma_statements.meta.json")
    parser.add_argument("--timeout", type=float, default=7200,
                        help="wall-clock budget for each Lean dump")
    args = parser.parse_args(argv)

    lean_root = args.lean_root.resolve()
    kinds = {kind.strip() for kind in args.kinds.split(",") if kind.strip()}

    if args.from_file is not None:
        dump_text = args.from_file.read_text()
        dump_source = _display_path(args.from_file)
        dump_command = f"read from {dump_source}"
    else:
        dump_command = (
            f"cd {_display_path(lean_root)} && lake env lean --run "
            f"{args.statement_dumper} --import {args.import_module} "
            f"--kinds {','.join(sorted(kinds))}")
        dump_text = _run_lean(
            lean_root,
            ["lake", "env", "lean", "--run", args.statement_dumper,
             "--import", args.import_module, "--kinds", ",".join(sorted(kinds))],
            args.timeout)
        dump_source = _display_path(lean_root / args.statement_dumper)

    modules: dict[str, str] | None = None
    modules_source: str | None = None
    modules_text: str | None = None
    if args.modules_file is not None:
        modules_text = args.modules_file.read_text()
        modules_source = _display_path(args.modules_file)
    elif args.from_file is None:
        modules_command = (
            f"cd {_display_path(lean_root)} && lake env lean --run "
            f"{args.module_dumper} --import {args.import_module}")
        modules_text = _run_lean(
            lean_root,
            ["lake", "env", "lean", "--run", args.module_dumper,
             "--import", args.import_module],
            args.timeout)
        modules_source = f"generated by: {modules_command}"
    if modules_text is not None:
        modules = read_module_map_text(modules_text)

    records = read_statement_dump(dump_text)
    if not records:
        raise SystemExit("the statement dump was empty; refusing to write a corpus")
    prepared, summary = prepare_statements(
        records, modules,
        drop_internal=not args.keep_internal,
        drop_equation_lemmas=args.drop_equation_lemmas,
        kinds=kinds)
    if not prepared:
        raise SystemExit("every declaration was filtered out; refusing to write a corpus")

    write_corpus(args.output, prepared)
    metadata = {
        "artifact": "mathlib_lemma_statements",
        "schema_version": 1,
        "command": " ".join(["python", _display_path(Path(__file__))] + sys.argv[1:]),
        "dump_command": dump_command,
        "dump_source": dump_source,
        "dump_sha256": sha256_text(dump_text),
        "dump_line_count": len(dump_text.splitlines()),
        "lean_toolchain": _toolchain(lean_root),
        "mathlib_revision": _mathlib_revision(lean_root),
        "kinds": sorted(kinds),
        "drop_internal": not args.keep_internal,
        "drop_equation_lemmas": args.drop_equation_lemmas,
        "modules_file": _display_path(args.modules_file) if args.modules_file else None,
        "modules_source": modules_source,
        "modules_sha256": sha256_text(modules_text) if modules_text is not None else None,
        **summary,
        "format": "gzip-compressed JSONL, sorted by name" if args.output.suffix == ".gz"
                  else "JSONL, sorted by name",
        "output": _display_path(args.output),
        "output_sha256": sha256_file(args.output),
        "code_revision": code_revision(),
        "code_state": working_tree_state(),
        "code_diff_sha256": code_diff_sha256(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "caveats": [
            "types are pretty-printed with the Lean delaborator, not re-elaborated",
            "a retrieval hit is not a verified lemma application; Lean is the authority",
            "private and compiler-generated names are dropped by default",
            "the corpus is retrieval input, not a proof corpus",
        ],
    }
    args.meta.parent.mkdir(parents=True, exist_ok=True)
    args.meta.write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({
        "output_count": summary["output_count"],
        "input_count": summary["input_count"],
        "dropped": summary["dropped"],
        "output": str(args.output),
        "meta": str(args.meta),
        "mathlib_revision": metadata["mathlib_revision"],
        "output_sha256": metadata["output_sha256"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
