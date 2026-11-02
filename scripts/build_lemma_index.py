#!/usr/bin/env python3
"""Build the lemma-name index from the pinned Mathlib environment.

The Lean side prints every constant name (``NeuralProof/DumpDeclarations.lean``);
this script sorts and deduplicates them, adds each name's last component (so an
unqualified reference such as ``range_eq_Ico`` resolves to ``Finset.range_eq_Ico``),
writes ``data/lemma_index.json.gz``, and records the Mathlib revision, toolchain,
command and hashes in a metadata file.  Use ``--from-file`` to rebuild from a
captured dump without invoking Lean.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from neuralproof.data.provenance import (  # noqa: E402
    code_diff_sha256,
    code_revision,
    sha256_file,
    sha256_text,
    working_tree_state,
)

_NAME = re.compile(r"^[^\s]+$")


def _display_path(path: Path) -> str:
    """A repo-relative path when possible, so provenance is not host-specific."""
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


def _read_dump_from_lean(lean_root: Path, dumper: str, timeout: float) -> str:
    command = ["lake", "env", "lean", "--run", dumper]
    completed = subprocess.run(command, cwd=lean_root, capture_output=True,
                               text=True, timeout=timeout)
    if completed.returncode != 0:
        raise SystemExit(
            "Lean declaration dump failed with exit status "
            f"{completed.returncode}:\n{completed.stderr.strip()}")
    return completed.stdout


def _names_from_dump(text: str) -> list[str]:
    # The dumper writes one name per line on stdout; Lean diagnostics go to
    # stderr.  Keep every whitespace-free token so a constant whose name starts
    # with ``error``, ``warning`` or ``info`` is not silently dropped.
    names = set()
    for line in text.splitlines():
        name = line.strip()
        if not name or not _NAME.match(name):
            continue
        names.add(name)
    return sorted(names)


def _index_names(constants: list[str]) -> list[str]:
    """Constant names plus every unqualified last component.

    Mathlib is normally used with namespaces open, so a source tactic may write
    ``range_eq_Ico`` for ``Finset.range_eq_Ico``.  Indexing the last component
    keeps the pre-filter from rejecting those references; it deliberately
    accepts some namespaces that would not elaborate, which only costs a Lean
    call and never a false rejection.
    """
    names = set(constants)
    names.update(name.rsplit(".", 1)[-1] for name in constants)
    return sorted(names)


def _write_index(path: Path, names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(names, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if path.suffix == ".gz":
        # A fixed mtime keeps the artifact byte-identical across rebuilds, so
        # the recorded SHA-256 pins the names rather than the build clock.
        path.write_bytes(gzip.compress(payload, 9, mtime=0))
    else:
        path.write_bytes(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lean-root", type=Path, default=REPO_ROOT / "lean")
    parser.add_argument("--dumper", default="NeuralProof/DumpDeclarations.lean")
    parser.add_argument("--from-file", type=Path,
                        help="read a captured declaration dump instead of running Lean")
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "data" / "lemma_index.json.gz")
    parser.add_argument("--meta", type=Path, default=REPO_ROOT / "data" / "lemma_index.meta.json")
    parser.add_argument("--timeout", type=float, default=3600,
                        help="wall-clock budget for the Lean dump")
    args = parser.parse_args(argv)

    lean_root = args.lean_root.resolve()
    if args.from_file is not None:
        dump_text = args.from_file.read_text()
        dump_source = _display_path(args.from_file)
        dump_command = f"read from {dump_source}"
    else:
        dump_text = _read_dump_from_lean(lean_root, args.dumper, args.timeout)
        dump_source = _display_path(lean_root / args.dumper)
        dump_command = f"cd {_display_path(lean_root)} && lake env lean --run {args.dumper}"

    constants = _names_from_dump(dump_text)
    if not constants:
        raise SystemExit("the declaration dump was empty; refusing to write an empty index")
    names = _index_names(constants)

    _write_index(args.output, names)
    metadata = {
        "artifact": "mathlib_lemma_index",
        "schema_version": 2,
        "command": " ".join(["python", _display_path(Path(__file__))] + sys.argv[1:]),
        "dump_command": dump_command,
        "dump_source": dump_source,
        "dump_sha256": sha256_text(dump_text),
        "dump_line_count": len(dump_text.splitlines()),
        "lean_toolchain": _toolchain(lean_root),
        "mathlib_revision": _mathlib_revision(lean_root),
        "constant_count": len(constants),
        "basename_count": len(names) - len(constants),
        "count": len(names),
        "format": "gzip-compressed JSON array" if args.output.suffix == ".gz" else "JSON array",
        "output": _display_path(args.output),
        "output_sha256": sha256_file(args.output),
        "code_revision": code_revision(),
        "code_state": working_tree_state(),
        "code_diff_sha256": code_diff_sha256(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "caveats": [
            "the index is a name set, not a proof that a name is applicable",
            "private and internal constant names are included as printed by Lean",
            "last components are indexed so unqualified names can resolve",
            "the pre-filter still treats identifiers in the goal state as known",
        ],
    }
    args.meta.parent.mkdir(parents=True, exist_ok=True)
    args.meta.write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({"count": len(names), "constant_count": metadata["constant_count"],
                      "output": str(args.output), "meta": str(args.meta),
                      "mathlib_revision": metadata["mathlib_revision"],
                      "output_sha256": metadata["output_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
