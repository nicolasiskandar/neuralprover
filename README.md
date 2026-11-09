# Neural Prover

Neural Prover is a LoRA fine-tuned language model for Lean 4 proof generation. It predict the next tactic from a Lean context and goal state. A bounded best-first search composes those tactics, and Lean's kernel decides whether the resulting proof is valid.

The harness exists to keep the model's output honest:

- **Lean is the acceptance authority.** A proof is reported as verified only after the reconstructed, placeholder-free declaration compiles and `#print axioms` shows no unexpected axioms. `sorry` and `admit` are rejected.
- **The prompt is canonical.** `neuralproof.models.prompt.format_tactic_prompt` is the single place a goal state becomes a prompt, so mined, training, and live inputs have the same shape.
- **Silence is not an error.** A completion containing no tactic is counted as a `silent_prediction`, not as a wrong tactic, and an empty candidate never reaches Lean. A 0/N run therefore says _why_ it was 0.

Interactive sessions are explicitly human-in-the-loop. They are useful for stepping through proofs and inspecting suggestions, but they are never counted as autonomous benchmark results.

## Demo
[![Neural Prover Demo](https://img.youtube.com/vi/rWPMdyb-cf4/0.jpg)](https://www.youtube.com/watch?v=rWPMdyb-cf4)

## The model

- **Base:** `HuggingFaceTB/SmolLM2-135M`, immutable revision `4e53f736cbb20a9a0f56b4c4bf378d9f306ff915`.
- **Adapter:** LoRA rank 8, alpha 16, dropout 0.05, targeting `q_proj` and `v_proj`.
- **Training:** one epoch, seed 17, on 3,976 proof-scope rows from the 200-file InfoTree corpus.
- **Task:** next-tactic prediction from the canonical context + proof-state prompt, up to 64 generated tokens. Multiple samples can feed best-first search.
- **Measured:** 21/342 exact tactic matches on the full eligible held-out set. With search, the LoRA adapter solved 6/50 held-out theorems versus 0/50 for the base model; all solved theorems were single-step.
- **Scope:** the adapter does not emit a complete proof by itself. Best-first search composes its tactic predictions, and Lean's kernel verifies the result.

## Quick start

```bash
uv venv --python python3.11 .venv
source .venv/bin/activate
uv pip install -e '.[test]'
cd lean && lake update && lake build && cd ..
python -m neuralproof.cli doctor
pytest -m "not lean"
```

Lean's version is pinned in `lean/lean-toolchain`, and Mathlib plus its transitive Lake dependencies are locked in `lean/lake-manifest.json`. A missing Lean toolchain or corpus becomes an explicit test skip with a reason, never a silent pass.

## Interactive proof stepping

`interact` opens a Lean-checked session. Every typed tactic is sent to Lean immediately; rejected tactics print Lean's error, and a completed proof is verified by the kernel and axiom check.

```bash
python -m neuralproof.cli interact --file lean/NeuralProof/Samples.lean
python -m neuralproof.cli interact \
  --theorem "theorem demo (p : Prop) (hp : p) : p" \
  --context "import Lean"
```

A session looks like this:

```text
Goals (1):
Goal 1: p : Prop
hp : p
⊢ p
Suggestions (goal-ranked):
  1. assumption
  2. trivial
  3. simp
  4. omega
  5. exact True.intro
Type a tactic, or :help for commands.
[0 tactics] > assumption
Lean: accepted — no goals remain
Kernel: VERIFIED (axioms: none)
Use :save [path] to write the proof.
```

### Commands

| Command        | Effect                                                  |
| -------------- | ------------------------------------------------------- |
| `<tactic>`     | Apply a tactic and print the goals Lean reports.        |
| `:goals`       | Re-inspect and print the current goals.                 |
| `:suggest [n]` | Show ranked predictor suggestions; nothing is applied.  |
| `:search`      | Run bounded best-first search from the current state.   |
| `:undo`        | Remove the last tactic.                                 |
| `:verify`      | Re-run the kernel and axiom check on the current proof. |
| `:save [path]` | Write the proof and a `.json` sidecar.                  |
| `:reset`       | Return to the initial goal.                             |
| `:help`        | List commands.                                          |
| `:quit`        | Exit the session.                                       |

### Suggestions and search

Suggestions are shown automatically after the initial goal, after each accepted step, after a rejection, and after `:undo`/`:reset`. They are **never applied automatically**; `--no-auto-suggest` turns the display off.

By default they are ordered by the current goal shape. For example, `rfl` is demoted when the two sides of an equality are not syntactically equal, while `omega` or `ac_rfl` is promoted when the goal and context fit. `--no-rank-suggestions` keeps the predictor's original order. The displayed order is a heuristic rank: it is not a probability, and it is not a promise that Lean will accept the tactic.

`:search` explores a bounded best-first tree from the current state using that same goal-ranked order. Its `--width` defaults to `--max-suggestions`, so the tactics shown by `:suggest` are the ones it tries first. A machine-found proof is loaded into the session only after the kernel and axiom check succeed.

Without `--tactics` or a model, the default portfolio is `rfl`, `trivial`, `assumption`, `simp`, `omega`, and `exact True.intro`, plus `ac_rfl` when the context imports Mathlib. Pass `--tactics "…"` (comma-separated or a JSON array) to supply your own candidates.

Other useful flags: `--model-id`, `--adapter`, and `--revision` load an HF predictor; `--max-suggestions` sets the default display count; `--nodes` and `--width` bound search; `--timeout` and `--save-dir` control execution and output.

Inaccessible-name markers such as `inst✝` or `x✝¹` are hidden in the rendered goals. This is display-only: `canonical_goal_state`, prompts, corpus rows, and verification keep Lean's exact text.

A saved proof gets a `.lean` file and a `.json` sidecar marked `"human_in_the_loop": true`, together with its history, verification result, declaration name, and axioms. Never mix these files with autonomous benchmark results.

## Pipeline

- `neuralproof.data` extracts, normalizes, and preprocesses Lean data.
- `neuralproof.lean` runs Lean, parses goal states, and verifies declarations.
- `neuralproof.models` formats prompts and loads the static or HF predictor.
- `neuralproof.search` runs bounded best-first search over Lean-checked successors.
- `neuralproof.evaluation` scores tactic prediction and whole-theorem search.
- `neuralproof.interactive` and `neuralproof.suggestions` provide the CLI session and goal-aware candidate ranking.

See [docs/architecture.md](docs/architecture.md) for the design and its deliberate limits.

## Commands

| Command                | Purpose                                                                                        |
| ---------------------- | ---------------------------------------------------------------------------------------------- |
| `doctor`               | Report the active Lean toolchain and Python version.                                           |
| `data extract`         | Conservative source parser plus Lean goal inspection and tactic replay.                        |
| `data trace`           | Raw native Lean 4 InfoTree tactic and goal export.                                             |
| `data normalize-trace` | Normalize source spans into supervised tactic JSONL, with exclusion stats.                     |
| `data trace-corpus`    | Resumable staged native InfoTree extraction for Mathlib files.                                 |
| `data corpus`          | Resumable staged Mathlib replay extraction.                                                    |
| `preprocess`           | Formatting, deterministic file-level splits, scope/label filtering, and a provenance manifest. |
| `train`                | Optional causal-LM LoRA SFT using Transformers and PEFT.                                       |
| `prove`                | Bounded best-first search using a static tactic list.                                          |
| `evaluate`             | Fixed-budget search evaluation of whole theorem headers.                                       |
| `evaluate-tactics`     | Held-out tactic-prediction comparison of base and adapter.                                     |
| `interact`             | Lean-checked interactive proof stepping with optional suggestions.                             |
| `report`               | Summarize result files under a directory.                                                      |

## Training and evaluation

Training uses the optional `train` extra on Python 3.11 or 3.12. On CPU-only machines, select the CPU wheel index explicitly:

```bash
uv pip install --python .venv/bin/python \
  --index-url https://pypi.org/simple \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --index-strategy unsafe-best-match \
  -e '.[train]' 'torch==2.6.0+cpu'
.venv/bin/python -m neuralproof.cli train \
  --data data/mathlib-info-tree-200/processed/train.jsonl \
  --model HuggingFaceTB/SmolLM2-135M \
  --revision 4e53f736cbb20a9a0f56b4c4bf378d9f306ff915 \
  --output experiments/mathlib-info-tree-lora-200-1epoch-canonical \
  --epochs 1 --seed 17
```

`--max-steps` is the step budget: `-1` trains the full number of epochs, and `0` is rejected. `--goal-scope proof` (the default) trains only on proof-global goal states, which is the distribution the live client reports.

The held-out tactic metric scores exact single-line source tactics, not proof success:

```bash
python -m neuralproof.cli evaluate-tactics \
  --data data/mathlib-info-tree-200/examples.jsonl \
  --adapter experiments/mathlib-info-tree-lora-200-1epoch-canonical \
  --revision 4e53f736cbb20a9a0f56b4c4bf378d9f306ff915 \
  --limit 342 --seed neuralproof-mathlib-info-tree-v1
```

See [docs/reproducibility.md](docs/reproducibility.md) for corpus builds, trace commands, artifact hashes, and the full evaluation commands.

## Current status and limits

The end-to-end pipeline is real: Lean extraction, preprocessing, LoRA training, prediction, best-first search, and kernel verification all run. Claims are deliberately narrow.

- **50-theorem held-out campaign** (`max_nodes=20`, `width=4`, `timeout=30s`): static baseline 7/50, base model 0/50, one-epoch LoRA 6/50, LoRA plus lemma filter 7/50. All solved theorems were single-step; no multi-step theorem was closed. See [experiments/benchmark-50/report.md](experiments/benchmark-50/report.md).
- **InfoTree corpus:** 200 sorted Mathlib files yielded 6,221 mined transitions; 246 (4.0 %) are not tactics and are excluded, leaving 5,975 rows split 4,789 / 773 / 413 by source file. Contexts are reconstructed and have not been independently replayed, so these are next-tactic supervision, not proof certificates.
- **Replay corpus:** 25 verified examples across 11 files, with only 1 validation and 2 test rows. Far too small for reliable claims.
- **Held-out tactic prediction:** a full-epoch LoRA reached 21/342 exact matches (6.14 %, Wilson 95 % CI [0.0405, 0.0920]) versus 0/342 for the base model. This is tactic exact match, not a proof-solving rate.
- **Retrieval and lemma filtering** are measurement/plumbing experiments, not demonstrated solve-rate gains. The filter is opt-in and never replaces Lean.
- **Interactive demonstrations** such as `omega` on `a + b = b + a` and `ac_rfl` on an abstract `AddCommMonoid` verify in Lean, but they are human-in-the-loop demos, not benchmark results.

The Lean client starts a fresh compiler process per tactic and replays the complete prefix. This isolates failures but is not a persistent REPL, and it costs seconds per cold invocation.

Full evidence, negative results, and limitations are in [docs/methodology.md](docs/methodology.md), [experiments/log.md](experiments/log.md), and [docs/reproducibility.md](docs/reproducibility.md).

## Tests

```bash
pytest                        # everything
pytest -m "not lean"          # no Lean toolchain needed
pytest -m lean                # only real Lean/Mathlib cases
pytest tests/test_interactive.py -q
python scripts/check_retrieval.py --no-dense
```

Markers are `lean`, `corpus`, `model`, and `slow`. The suite covers the label policy, prompt canonicalization, step budgets, completion boundaries, exclusion counters, corpus invariants, and real Lean proof checks.

## Repository layout

```text
neuralproof/   LoRA training/inference plus data, Lean, search, evaluation, and interactive modules
lean/          pinned Lean 4 and Mathlib project
tests/         pytest suite, including real-Lean cases
configs/       experiment settings
docs/          architecture, corpus, methodology, reproducibility
experiments/   run artifacts; experiments/log.md is the tracked log
data/          generated corpora and indexes; large artifacts are not committed
scripts/       index builders, retrieval checks, benchmark campaigns
```

## Documentation

- [docs/architecture.md](docs/architecture.md): modules, data record, search, and interactive sessions.
- [docs/mathlib-corpus.md](docs/mathlib-corpus.md): corpus schema and limitations.
- [docs/methodology.md](docs/methodology.md): research design, controls, and experimental status.
- [docs/reproducibility.md](docs/reproducibility.md): pinned versions, commands, and artifact provenance.
- [experiments/log.md](experiments/log.md): chronological record of runs and findings.

Mathlib-derived sample data is attributed in [data/raw/MATHLIB-NOTICE.md](data/raw/MATHLIB-NOTICE.md).
