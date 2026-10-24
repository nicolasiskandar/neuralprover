# Repository Guidelines

## Project Structure

- `neuralproof/` contains the Python CLI and the data, Lean-client, model, search, and evaluation modules.
- `lean/` is the pinned Lean 4 and Mathlib project; the toolchain and dependency lock are in `lean/lean-toolchain` and `lean/lake-manifest.json`.
- `tests/` contains the `pytest` suite, including tests that invoke real Lean and Mathlib.
- `configs/` stores experiment settings; `docs/` describes methods and reproducibility; `experiments/log.md` records actual runs.
- `data/` and `experiments/` may contain generated corpora and model artifacts. Do not commit large generated datasets or checkpoints.

## Build, Test, and Run

- `pytest` runs the full test suite; `pytest -m "not lean"` runs the part that does not need the Lean toolchain, and `pytest -m lean` runs only the cases that invoke it.
- `cd lean && lake build` builds the pinned Lean project; `python -m neuralproof.cli doctor` checks the local Lean setup.
- `python -m neuralproof.cli data trace --file <file.lean> --output <trace.json>` exports native InfoTree data.
- `python -m neuralproof.cli data trace-corpus --files 200 --output data/mathlib-info-tree-200` starts or resumes staged extraction; inspect its summary and per-file stats.
- `python -m neuralproof.cli preprocess --input <examples.jsonl> --output <processed-dir>` prepares model prompts.
- Use `train --max-steps 100` for a bounded CPU pilot. `evaluate-tactics` compares base and adapter prediction on a fixed held-out sample.

## Coding and Testing Conventions

Use four spaces for Python indentation, `snake_case` for modules/functions/variables, and `PascalCase` for classes. Keep data extraction, Lean execution, prediction, search, and metrics independently testable. Add `test_*.py` cases for new behavior; include fixture-based tests for schemas and real Lean tests when changing proof execution. Do not silently skip unavailable Lean or model dependencies.

Lean's kernel is the authority for proof acceptance. Never count generated text, model confidence, or an apparent closed goal as a verified theorem without final Lean verification. Keep extraction failures and experiment budgets visible in machine-readable output and `experiments/log.md`.

## Commits and Pull Requests

No Git history is available in this workspace to establish a repository-specific commit convention. Prefer concise imperative messages, optionally scoped (for example, `data: add resumable InfoTree extraction`). PRs should summarize behavior and limitations, list test/build commands and outcomes, identify data/model revisions and budgets for experiment changes, and link any related issue. Do not present unverified traces or pilot metrics as proof-solving results.
