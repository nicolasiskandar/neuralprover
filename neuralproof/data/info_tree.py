"""Native Lean 4 InfoTree tracing through the pinned Lean frontend driver."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from neuralproof.data.extraction import MATHLIB_REVISION


def trace_file(source_file: str | Path, *, project_dir: str | Path | None = None,
               timeout: float = 300) -> dict[str, Any]:
    project = Path(project_dir or Path(__file__).parents[2] / "lean").resolve()
    source = Path(source_file)
    if not source.is_absolute():
        source = source.resolve()
    driver = project / "NeuralProof" / "TraceMathlib.lean"
    cmd = ["lake", "env", "lean", "--run", str(driver), str(source)]
    proc = subprocess.run(cmd, cwd=project, capture_output=True, text=True,
                          timeout=timeout)
    if proc.returncode:
        raise RuntimeError((proc.stdout + proc.stderr).strip() or f"Lean exited {proc.returncode}")
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    try:
        payload = json.loads(lines[-1]) if lines else []
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Lean tracer returned malformed JSON: {proc.stdout[-2000:]}") from exc
    try:
        provenance = source.relative_to(project / ".lake" / "packages" / "mathlib").as_posix()
        revision: str | None = MATHLIB_REVISION
    except ValueError:
        provenance = str(source)
        revision = None
    if isinstance(payload, dict):
        traces = payload.get("tactics", [])
        commands = payload.get("commands", [])
    else:  # schema compatibility with traces emitted by the initial driver
        traces, commands = payload, []
    return {
        "schema_version": 2,
        "backend": "lean4_info_tree",
        "source_file": provenance,
        "source_revision": revision,
        "traces": traces,
        "commands": commands,
        "tactic_nodes": len(traces),
        "command_nodes": len(commands),
        "completed_nodes": sum(bool(t.get("completed")) for t in traces),
    }


def write_trace(source_file: str | Path, output: str | Path, **kwargs: Any) -> dict[str, Any]:
    result = trace_file(source_file, **kwargs)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result
