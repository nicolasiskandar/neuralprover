"""Machine-readable provenance for generated artifacts.

Every processed dataset records the command that produced it, the digest of its
input, the row counts, and the policies in force, so a result can be checked
against the artifacts it was computed from.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path) -> str:
    """SHA-256 of a file, or `None` when it does not exist."""
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def code_revision() -> str | None:
    """The current git revision, or `None` when it cannot be determined."""
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def working_tree_state() -> str:
    """Whether the working tree matches `HEAD` (`clean`/`dirty`/`unknown`).

    Artifacts built from an uncommitted tree must say so, otherwise the
    recorded revision does not describe the code that produced them.
    """
    try:
        proc = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                              text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if proc.returncode != 0:
        return "unknown"
    return "dirty" if proc.stdout.strip() else "clean"


def code_diff_sha256() -> str | None:
    """Digest of the uncommitted patch, so a dirty tree is still identifiable.

    `git diff` does not mention untracked files, but a new module that the
    artifact depends on is part of the code that produced it.  Untracked
    files are therefore folded into the digest by path and content, so the
    manifest describes the tree as it is and not only the tracked part of it.
    """
    try:
        patch = subprocess.run(["git", "diff", "HEAD"], capture_output=True,
                               text=True, timeout=30)
        status = subprocess.run(["git", "status", "--porcelain", "-uall"],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if patch.returncode != 0 or status.returncode != 0:
        return None
    digest = hashlib.sha256()
    digest.update(patch.stdout.encode("utf-8"))
    for line in status.stdout.splitlines():
        if not line.startswith("?? "):
            continue
        path = line[3:].strip().strip('"')
        digest.update(b"\0untracked\0" + path.encode("utf-8") + b"\0")
        digest.update((sha256_file(path) or "").encode("utf-8"))
    return digest.hexdigest()


def current_command() -> str:
    """The command line that produced the artifact."""
    return "python -m neuralproof.cli " + " ".join(sys.argv[1:])


def write_manifest(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write a provenance manifest next to the artifacts it describes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path
