# NeuralProof

NeuralProof is a research codebase for Lean 4 tactic prediction and proof search. It is deliberately Python-first, but Lean—not model output—is the acceptance authority. The current environment supports a genuine kernel-checked Lean 4 pipeline, a 200-file staged Mathlib corpus, native InfoTree tracing, and a CPU LoRA smoke run. Full Mathlib extraction and controlled neural evaluation remain incomplete.

## Environment assessment

Observed 2026-10-19: Lean/Lake 4.35.0, Python 3.14.4 default and Python 3.11.17 available, 16 logical CPU threads, about 15 GiB RAM, no visible NVIDIA GPU, and ample workspace disk. `uv` is present. Mathlib v4.35.0 and pinned Lake dependencies have been fetched; Lake reused a compatible cache for 9,030 files. A one-epoch CPU LoRA smoke run used the immutable `HuggingFaceTB/SmolLM2-135M` revision in `configs/model.yaml`; its tiny training loss is not an evaluation metric. Adapter inference ran but generated unusable tactics on the attempted theorem, so no neural solve is claimed.

## Install and run

```bash
uv venv --python python3.11 .venv
source .venv/bin/activate
uv pip install -e .
cd lean && lake update && lake build && cd ..
python -m neuralproof.cli doctor
python -m unittest discover -s tests -v
python -m neuralproof.cli data extract --limit 100
python -m neuralproof.cli data extract --mathlib --module Mathlib/Data/Nat/Basic.lean --limit 100 --output data/raw/mathlib_mined.jsonl --stats data/raw/mathlib_mined_stats.json
python -m neuralproof.cli preprocess
python -m neuralproof.cli evaluate --data data/processed/train.jsonl --output experiments/smoke/results.jsonl
```

Lean 4 must be installed with elan. Its selected version is pinned in `lean/lean-toolchain`; Mathlib and all transitive Lake dependencies are locked in `lean/lake-manifest.json`. The default extractor mines simple local examples. With `--mathlib`, the conservative pilot mines simple one-tactic declarations from the pinned Mathlib source, replays and verifies them, and records provenance and failures. Run `python scripts/collect_mathlib_pilot.py` to reproduce the one-row clean pilot. This is a small real-data pilot, not a general Lean syntax or elaboration-data extractor. The checked-in sample has attribution in `data/raw/MATHLIB-NOTICE.md`.

Native tactic-state traces are available through Lean's pinned frontend `InfoTree` interface:

```bash
python -m neuralproof.cli data trace \
  --file lean/.lake/packages/mathlib/Mathlib/Algebra/AddConstMap/Basic.lean \
  --output data/traces/addconstmap-basic.json
```

The command exports tactic syntax and before/after goals from actual elaboration. Nested tactics and macro combinators create overlapping nodes, so this is raw trace data and should be filtered before constructing next-tactic examples. The resumable staged corpus command uses the verified replay subset and retains per-file extraction statistics. Its reconstructed context uses source imports and active directives while excluding the theorem under extraction; examples that rely on earlier declarations from that same source file are reported as replay failures:

```bash
python -m neuralproof.cli data corpus --files 200 --per-file 5 --output data/mathlib-200
```

It deterministically selects sorted source paths from the pinned Mathlib checkout, keeps a file-level split, and checkpoints each completed file. See [docs/mathlib-corpus.md](docs/mathlib-corpus.md) for the schema and limitations.

For LoRA, use Python 3.11 or 3.12 for the pinned training stack and provide a local JSONL dataset with `context`, `goal_state`, and `target_tactic`. The observed Python 3.14 environment is suitable for the standard-library Lean MVP, but is outside the pinned training extra's supported range. On CPU-only machines, use the official CPU wheel index so `uv` does not select the much larger CUDA build:

```bash
uv pip install --python .venv/bin/python \
  --index-url https://pypi.org/simple \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --index-strategy unsafe-best-match \
  -e '.[train]' 'torch==2.6.0+cpu'
.venv/bin/python -m neuralproof.cli train \
  --data data/mathlib-200/processed/train.jsonl \
  --model HuggingFaceTB/SmolLM2-135M \
  --revision 4e53f736cbb20a9a0f56b4c4bf378d9f306ff915 \
  --output experiments/smol-lora-clean-smoke --epochs 1 --seed 17
```

The earlier CPU run on five rows from the superseded pilot is historical debugging only. A clean CPU run trained one epoch on 22 examples (22 steps, loss 4.4752). On the same two test theorems and a 6-node/width-3 search budget, the base and LoRA models each verified 0/2; the Wilson interval is [0, 0.658] for either rate. This sample is too small for meaningful model-quality claims. Traces are in `experiments/clean-base-test/` and `experiments/clean-lora-test/`.

Run only on completed/supported data when measuring generalization. The corpus preprocess split is file-level and deterministic; these tiny validation/test sets are not evaluation evidence.

## Current commands

- `doctor`: reports the active Lean toolchain and Python version.
- `data extract`: conservative source parser plus Lean goal inspection and tactic replay.
- `data trace`: raw native Lean 4 InfoTree tactic and goal export.
- `data normalize-trace`: conservative source-span normalization into supervised tactic JSONL, with exclusion stats.
- `data trace-corpus`: resumable staged native InfoTree extraction for Mathlib files.
- `data corpus`: resumable staged Mathlib replay extraction.
- `preprocess`: JSONL formatting and deterministic file-level partitioning.
- `train`: optional causal LM LoRA SFT using Transformers and PEFT.
- `prove`: bounded best-first search using a static tactic list; pass a JSON array to preserve commas inside Lean tactics.
- `evaluate`: fixed-node/wall-time search evaluation, writes per-problem JSONL.
- `report`: summarizes result files under a directory.

The static predictor is a testing baseline, not a language model. `neuralproof.models.predictor.load_hf_predictor` loads an HF base model or adapter; pass `--model-id`, `--adapter`, and an immutable `--revision` to `prove`/`evaluate` when available. Search priority can be varied with `--priority bfs`, deduplication can be disabled with `--no-deduplicate`, and width/node limits expose small search ablations. No result should be labeled a base-vs-LoRA comparison until the same held-out set and budget have been executed with both weights.

## Soundness and current limits

The Lean client starts a fresh compiler process per tactic, replays the complete prefix, and asks Lean to print goals. This isolates candidate failures but costs seconds per cold invocation; it is not a persistent REPL. A tactic transition that closes the goal is accepted only after the reconstructed placeholder-free declaration compiles. `sorry` and `admit` are rejected by the final verifier. Multiple goals can be replayed, but state identity is currently the tactic prefix, not semantic environment equivalence; deduplication by printed goals is deliberately not used.

This MVP checks for unexpected axioms (allowing Lean's standard foundational `propext`, `Classical.choice`, and `Quot.sound`), but does not yet handle arbitrary syntax in supervised replay extraction, provide retrieval, compute pass@10, or measure GPU usage. The staged corpus currently contains 25 verified examples from 11 files, but validation/test contain only 1 and 2 examples and are far too small for reliable claims. The checked-in one-row Mathlib pilot and three additional Mathlib-backed local smoke examples exercise tactic replay. This is not a benchmark. Remaining gaps are recorded in `docs/methodology.md` and `experiments/log.md`.
