"""Kernel-checked tactic transitions against an original Mathlib proof.

The acceptance study asks a narrow question: given the source position of a
held-out tactic, does Lean accept a replacement at that position?  The
replacement is substituted into the smallest enclosing tactic when the source
target is only a fragment (for example a lemma name inside ``simp_rw [...]``),
and the rest of the original proof is closed with ``sorry`` so the harness can
finish elaborating.  A successful harness is evidence that the replacement was
accepted in context, never a proof of the declaration.

Lean remains the authority.  This module deliberately does not fall back to
replaying the complete declaration: that fallback would hide a rejected
replacement behind the original proof.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neuralproof.data.extraction import MATHLIB_REVISION
from neuralproof.data.info_tree import trace_file
from neuralproof.data.provenance import sha256_file
from neuralproof.lean.client import _parse_messages

_TACTIC_PREFIX = "Lean.Parser.Tactic."
_WRAPPERS = frozenset({
    "tacticSeq", "tacticSeq1Indented", "tacticSeq1", "tactic", "byTactic",
})
TRACE_SCHEMA_VERSION = 1


class TransitionError(ValueError):
    """The source position cannot be represented as a standalone transition."""


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _kind_leaf(kind: str) -> str:
    return kind.rsplit(".", 1)[-1]


def _is_wrapper(kind: str) -> bool:
    return _kind_leaf(kind) in _WRAPPERS


def _is_tactic_node(kind: str) -> bool:
    """A parser tactic that can stand in for a source span in the harness."""
    return kind.startswith(_TACTIC_PREFIX) and not _is_wrapper(kind)


def _tail(text: str, limit: int = 300) -> str:
    compact = " ".join((text or "").split())
    return compact[:limit]


@dataclass(frozen=True)
class TransitionSpan:
    """The source target and the enclosing tactic used for substitution."""

    target_start: int
    target_end: int
    container_start: int
    container_end: int
    target_kind: str
    container_kind: str

    @property
    def is_fragment(self) -> bool:
        return (self.container_start, self.container_end) != (
            self.target_start, self.target_end)

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_start": self.target_start,
            "target_end": self.target_end,
            "container_start": self.container_start,
            "container_end": self.container_end,
            "target_kind": self.target_kind,
            "container_kind": self.container_kind,
            "is_fragment": self.is_fragment,
        }


@dataclass(frozen=True)
class Harness:
    """A complete Lean file and the span that was substituted into it."""

    text: bytes
    span: TransitionSpan
    proof_start: int
    body_end: int
    indent: bytes
    close_remaining: bool = False
    inline_by: bool = False


@dataclass(frozen=True)
class HarnessRun:
    returncode: int | None
    messages: tuple[dict[str, Any], ...]
    stdout: str
    stderr: str
    timed_out: bool
    elapsed_seconds: float


@dataclass(frozen=True)
class Classification:
    status: str
    reason: str | None
    errors: tuple[str, ...] = ()
    diagnostic: str = ""


def find_transition_span(trace: dict[str, Any], owner: str, start: int | None,
                         end: int | None, *,
                         within: tuple[int, int] | None = None) -> TransitionSpan:
    """Find the smallest strict non-wrapper tactic that contains the target.

    A target that is a complete tactic has no strict container and is used as
    its own substitution span.  A fragment such as a lemma name inside
    ``simp_rw [...]`` is substituted into the enclosing tactic instead.
    ``within`` restricts containers to one proof body, so a nested ``by``
    cannot select its enclosing ``have`` as the substitution point.
    """
    if start is None or end is None or start < 0 or end <= start:
        raise TransitionError("invalid_tactic_span")

    containers: list[tuple[int, int, int, str]] = []
    for node in trace.get("traces", []):
        node_start, node_end = _int(node.get("source_start")), _int(node.get("source_end"))
        if node_start is None or node_end is None or node_end <= node_start:
            continue
        kind = str(node.get("syntax_kind", ""))
        if not _is_tactic_node(kind):
            continue
        declaration = str(node.get("declaration", "") or "")
        if declaration and owner and declaration != owner:
            continue
        if within is not None and not (within[0] <= node_start and node_end <= within[1]):
            continue
        if not (node_start <= start and end <= node_end):
            continue
        if node_start == start and node_end == end:
            continue
        containers.append((node_end - node_start, node_start, node_end, kind))

    if containers:
        _, container_start, container_end, container_kind = min(
            containers, key=lambda item: (item[0], item[1], item[3]))
        target_kind = "fragment"
    else:
        container_start, container_end = start, end
        container_kind = ""
        target_kind = "tactic"
    return TransitionSpan(
        target_start=start, target_end=end,
        container_start=container_start, container_end=container_end,
        target_kind=target_kind, container_kind=container_kind)


def _proof_body(trace: dict[str, Any], owner: str,
                start: int) -> tuple[int, int, int]:
    """Return the proof start, the `by` keyword boundary, and the proof end."""
    proofs = []
    for node in trace.get("traces", []):
        if node.get("syntax_kind") != "Lean.Parser.Term.byTactic":
            continue
        if owner and str(node.get("declaration", "") or "") != owner:
            continue
        node_start, node_end = _int(node.get("source_start")), _int(node.get("source_end"))
        if node_start is None or node_end is None:
            continue
        if node_start <= start <= node_end:
            proofs.append((node_end - node_start, node_start, node_end))
    if not proofs:
        raise TransitionError("proof_span_not_found")
    _, proof_start, proof_end = min(proofs, key=lambda item: (item[0], item[1]))

    for node in trace.get("traces", []):
        if node.get("syntax_kind") != "by":
            continue
        if owner and str(node.get("declaration", "") or "") != owner:
            continue
        node_start, node_end = _int(node.get("source_start")), _int(node.get("source_end"))
        if node_start == proof_start and node_end is not None and node_end >= proof_start:
            return proof_start, node_end, proof_end
    raise TransitionError("proof_body_boundary_not_found")


def _declaration_end(trace: dict[str, Any], start: int, end: int,
                     default: int) -> int:
    """The end of the smallest command containing the target.

    Keeping the source between the proof end and this boundary preserves
    following structure fields (``where left ... right ...``) and the outer
    proof tail when the target sits inside a nested ``by``.
    """
    candidates = []
    for command in trace.get("commands", []):
        command_start = _int(command.get("source_start"))
        command_end = _int(command.get("source_end"))
        if command_start is None or command_end is None:
            continue
        if command_start <= start and end <= command_end:
            candidates.append((command_end - command_start, command_start, command_end))
    if not candidates:
        return default
    _, _, command_end = min(candidates, key=lambda item: (item[0], item[1]))
    return command_end


def build_harness(trace: dict[str, Any], source_file: str | Path,
                  row: dict[str, Any], replacement: str | bytes | None = None, *,
                  project_dir: str | Path | None = None,
                  close_remaining: bool = False) -> Harness:
    """Substitute a replacement into the source and optionally close goals.

    ``replacement`` is inserted in place of the target span *inside* its
    enclosing tactic.  With ``None`` the original source text is used, which
    self-checks that the reconstructed transition is representable.  When
    ``close_remaining`` is true the original proof after the transition is
    discarded and remaining goals are closed with ``all_goals sorry`` so the
    self-check can finish even when the target leaves goals open.  Candidate
    checks must leave this false: a candidate that applies but leaves goals
    has to be classified as accepted, not silently closed by ``sorry``.
    """
    del project_dir  # accepted for call-site symmetry with run_harness
    path = Path(source_file)
    raw = path.read_bytes()
    start = _int(row.get("source_start"))
    end = _int(row.get("source_end"))
    if start is None or end is None:
        raise TransitionError("invalid_tactic_span")
    if start < 0 or end <= start:
        raise TransitionError("invalid_tactic_span")
    owner = str(row.get("source_declaration", "") or "")
    proof_start, body_end, proof_end = _proof_body(trace, owner, start)
    span = find_transition_span(trace, owner, start, end,
                                within=(proof_start, proof_end))
    declaration_end = _declaration_end(trace, span.target_start, span.target_end,
                                       proof_end)

    if not (0 <= body_end <= span.container_start):
        raise TransitionError("proof_body_after_transition")
    if not (0 <= span.container_start <= span.target_start
            and span.target_end <= span.container_end <= proof_end <= len(raw)):
        raise TransitionError("transition_span_outside_source")

    if replacement is None:
        replacement_bytes = raw[span.target_start:span.target_end]
    elif isinstance(replacement, str):
        replacement_bytes = replacement.encode("utf-8")
    else:
        replacement_bytes = bytes(replacement)

    line_start = raw.rfind(b"\n", 0, span.container_start) + 1
    indent = raw[line_start:span.container_start]
    indent = indent[:len(indent) - len(indent.lstrip(b" \t"))]

    # A proof written as ``... := by simp`` keeps the first tactic on the
    # ``by`` line.  A following standalone ``all_goals`` would then be parsed
    # as a new command, so continue the tactic sequence with ``;`` instead.
    inline_by = b"\n" not in raw[body_end:span.container_start]

    harness = (
        raw[:body_end]
        + raw[body_end:span.container_start]
        + raw[span.container_start:span.target_start]
        + replacement_bytes
        + raw[span.target_end:span.container_end]
    )
    if close_remaining and inline_by:
        harness += b"; all_goals sorry\n"
    elif close_remaining:
        harness += b"\n" + indent + b"all_goals sorry\n"
    # Preserve the rest of the enclosing declaration: following structure
    # fields, or the outer proof tail when the target is in a nested ``by``.
    harness += raw[proof_end:declaration_end]

    return Harness(text=harness, span=span, proof_start=proof_start,
                   body_end=body_end, indent=indent,
                   close_remaining=close_remaining, inline_by=inline_by)


def run_harness(text: bytes | str, *, project_dir: str | Path | None = None,
                timeout: float = 120,
                prefix: str = "neuralproof-accept-") -> HarnessRun:
    """Run one harness through the pinned Lean toolchain."""
    project = Path(project_dir or Path(__file__).parents[2] / "lean").resolve()
    lean = shutil.which("lean")
    lake = shutil.which("lake")
    if lean is None:
        raise RuntimeError("Lean executable not found; install elan and the pinned toolchain")

    payload = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".lean", dir=project,
                                         delete=False) as stream:
            stream.write(payload)
            temp_path = Path(stream.name)
        command = ([lake, "env", lean, "--json", str(temp_path)]
                   if lake else [lean, "--json", str(temp_path)])
        started = time.perf_counter()
        try:
            proc = subprocess.run(command, cwd=project, capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return HarnessRun(None, (), "", "", True,
                              time.perf_counter() - started)
        return HarnessRun(proc.returncode, _parse_messages(proc.stdout),
                          proc.stdout, proc.stderr, False,
                          time.perf_counter() - started)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def classify_output(run: HarnessRun) -> Classification:
    """Classify a Lean run as closed, accepted, rejected, or timed out.

    ``accepted`` is intentionally narrow: the only error must be Lean's
    ``unsolved goals`` report.  A parse error, an unknown tactic, or a failed
    side condition is a rejection even when it leaves goals open.
    """
    if run.timed_out:
        return Classification("timeout", "lean_timeout")

    errors = tuple(str(message.get("data", ""))
                   for message in run.messages
                   if message.get("severity") == "error")
    if run.returncode == 0 and not errors:
        return Classification("closed", None)

    if errors and all("unsolved goals" in error for error in errors):
        return Classification("accepted", "unsolved_goals", errors,
                              "\n".join(errors)[-4000:])

    if not errors:
        combined = run.stderr.strip() or run.stdout.strip()
        if "unsolved goals" in combined:
            return Classification("accepted", "unsolved_goals", (),
                                  combined[-4000:])
        return Classification("rejected", _tail(combined) or "lean_error", (),
                              combined[-4000:])

    return Classification("rejected", _tail(errors[0]), errors,
                          "\n".join(errors)[-4000:])


def resolve_source(source_file: str | Path, *,
                   project_dir: str | Path | None = None,
                   mathlib_root: str | Path | None = None) -> Path:
    """Resolve a corpus-relative Mathlib path to a checked-out source file."""
    project = Path(project_dir or Path(__file__).parents[2] / "lean").resolve()
    root = Path(mathlib_root) if mathlib_root is not None else (
        project / ".lake" / "packages" / "mathlib")
    path = Path(source_file)
    if path.is_absolute():
        if path.is_file():
            return path
        raise FileNotFoundError(f"source file not found: {path}")
    for candidate in (root / path, project / path):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"source file {source_file!r} not found under {root} or {project}")


class TraceCache:
    """Load or regenerate InfoTree traces, keyed by source content and toolchain."""

    def __init__(self, project_dir: str | Path | None = None,
                 cache_dir: str | Path | None = None, *, refresh: bool = False,
                 timeout: float = 300) -> None:
        self.project_dir = Path(
            project_dir or Path(__file__).parents[2] / "lean").resolve()
        self.mathlib_root = self.project_dir / ".lake" / "packages" / "mathlib"
        self.cache_dir = Path(cache_dir) if cache_dir is not None else (
            Path(__file__).parents[2] / "data" / "cache" / "info-tree-traces")
        self.refresh = refresh
        self.timeout = timeout
        self.generated: list[str] = []
        self.loaded: list[str] = []
        self._lock = threading.Lock()
        self._toolchain = self._read_toolchain()

    def _read_toolchain(self) -> str | None:
        path = self.project_dir / "lean-toolchain"
        if not path.is_file():
            return None
        return path.read_text().strip() or None

    def source_path(self, source_file: str | Path) -> Path:
        return resolve_source(source_file, project_dir=self.project_dir,
                              mathlib_root=self.mathlib_root)

    def _relative_name(self, source_path: Path) -> str:
        try:
            return source_path.relative_to(self.mathlib_root).as_posix()
        except ValueError:
            return str(source_path)

    def _names(self, source_path: Path) -> tuple[str, Path, Path]:
        relative = self._relative_name(source_path)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", relative).strip("_")
        if len(safe) > 180:
            safe = safe[:180]
        return relative, self.cache_dir / f"{safe}.json", (
            self.cache_dir / f"{safe}.meta.json")

    def _expected_meta(self, source_path: Path) -> dict[str, Any]:
        relative = self._relative_name(source_path)
        revision = None if Path(relative).is_absolute() else MATHLIB_REVISION
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "source_file": relative,
            "source_sha256": sha256_file(source_path),
            "mathlib_revision": revision,
            "lean_toolchain": self._toolchain,
        }

    @staticmethod
    def _matches(recorded: Any, expected: dict[str, Any]) -> bool:
        if not isinstance(recorded, dict):
            return False
        return all(recorded.get(key) == value for key, value in expected.items())

    def get(self, source_file: str | Path) -> dict[str, Any]:
        source_path = self.source_path(source_file)
        _, trace_path, meta_path = self._names(source_path)
        expected = self._expected_meta(source_path)

        with self._lock:
            if not self.refresh and trace_path.is_file() and meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text())
                    if self._matches(meta, expected):
                        trace = json.loads(trace_path.read_text())
                        if isinstance(trace, dict) and "traces" in trace:
                            self.loaded.append(str(source_path))
                            return trace
                except (OSError, json.JSONDecodeError):
                    pass

            trace = trace_file(source_path, project_dir=self.project_dir,
                               timeout=self.timeout)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {**expected, "tactic_nodes": len(trace.get("traces", [])),
                       "command_nodes": len(trace.get("commands", []))}
            self._write_atomic(trace_path, json.dumps(trace, ensure_ascii=False))
            self._write_atomic(meta_path, json.dumps(payload, indent=2) + "\n")
            self.generated.append(str(source_path))
            return trace

    @staticmethod
    def _write_atomic(path: Path, text: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text)
        temporary.replace(path)
