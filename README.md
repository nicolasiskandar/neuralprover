# NeuralProof

NeuralProof is a research codebase for Lean 4 tactic prediction and proof search. It is deliberately Python-first, but Lean—not model output—is the acceptance authority. The current environment supports a genuine kernel-checked Lean 4 pipeline, a 200-file staged Mathlib corpus, native InfoTree tracing, and a CPU LoRA training run. Full Mathlib extraction and controlled neural evaluation remain incomplete.

Two properties of the harness matter more than the current numbers, because they decide whether any number is interpretable:

- **The prompt is canonical.** `neuralproof.models.prompt.format_tactic_prompt` is the single place where a goal state becomes a prompt. Every mined row, every training example, and every live prediction goes through it, so the model is never shown a goal state in one shape and asked about it in another.
- **The metric separates silence from error.** A completion that contains no tactic is counted as a `silent_prediction`, not as a wrong tactic, and a candidate that is empty never reaches Lean. A 0/N run therefore says *why* it was 0.

## Environment assessment

Observed 2026-10-19: Lean/Lake 4.35.0, Python 3.14.4 default and Python 3.11.17 available, 16 logical CPU threads, about 15 GiB RAM, no visible NVIDIA GPU, and ample workspace disk. `uv` is present. Mathlib v4.35.0 and pinned Lake dependencies have been fetched; Lake reused a compatible cache for 9,030 files. A one-epoch CPU LoRA smoke run used the immutable `HuggingFaceTB/SmolLM2-135M` revision in `configs/model.yaml`; its tiny training loss is not an evaluation metric. Adapter inference ran but generated unusable tactics on the attempted theorem, so no neural solve is claimed.

## Install and run

```bash
uv venv --python python3.11 .venv
source .venv/bin/activate
uv pip install -e '.[test]'
cd lean && lake update && lake build && cd ..
python -m neuralproof.cli doctor
pytest
python -m neuralproof.cli data extract --limit 100
python -m neuralproof.cli data extract --mathlib --module Mathlib/Data/Nat/Basic.lean --limit 100 --output data/raw/mathlib_mined.jsonl --stats data/raw/mathlib_mined_stats.json
python -m neuralproof.cli preprocess
python -m neuralproof.cli evaluate --data data/processed/train.jsonl --output experiments/smoke/results.jsonl
```

## Tests

The suite is `pytest`. It runs offline and never reaches the network; a missing
Lean toolchain or corpus becomes a skip with a reason, not a silent pass.

```bash
pytest                        # everything
pytest -m "not lean"          # the part that needs no Lean toolchain (fast)
pytest -m lean                # only the cases that invoke Lean and Mathlib
pytest tests/test_predictor.py -q
python scripts/check_retrieval.py --no-dense   # corpus + BM25, no model
python scripts/check_retrieval.py              # adds dense/hybrid and a held-out sanity run
```

Markers are `lean` (needs the pinned toolchain), `corpus` (needs a corpus that
is checked out under `data/`), `model` (needs torch, transformers and a local
model cache) and `slow`. The suite covers the label policy, the prompt
canonicalisation, the step budget, the completion boundary, the exclusion
counters, and the invariants of the generated corpora, next to the real Lean
proof checks.

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
  --data data/mathlib-info-tree-200/processed/train.jsonl \
  --model HuggingFaceTB/SmolLM2-135M \
  --revision 4e53f736cbb20a9a0f56b4c4bf378d9f306ff915 \
  --output experiments/mathlib-info-tree-lora-200-1epoch-canonical --epochs 1 --seed 17
```

`--max-steps` is the step budget. It defaults to `-1`, which trains for the full number of epochs; `0` is rejected, because `TrainingArguments` reads any non-negative budget as a hard limit and would end the run after its first step. `--goal-scope proof` (the default) trains only on rows whose mined goal state is the proof-global goal list, which is the only state the live client reports; a focus-local state is a different input distribution.

The earlier CPU run on five rows from the superseded pilot is historical debugging only. A clean CPU run trained one epoch on 22 examples (22 steps, loss 4.4752). On the same two test theorems and a 6-node/width-3 search budget, the base and LoRA models each verified 0/2; the Wilson interval is [0, 0.658] for either rate. This sample is too small for meaningful model-quality claims. Traces are in `experiments/clean-base-test/` and `experiments/clean-lora-test/`.

Run only on completed/supported data when measuring generalization. The corpus preprocess split is file-level and deterministic; these tiny validation/test sets are not evaluation evidence.

## Current commands

- `doctor`: reports the active Lean toolchain and Python version.
- `data extract`: conservative source parser plus Lean goal inspection and tactic replay.
- `data trace`: raw native Lean 4 InfoTree tactic and goal export.
- `data normalize-trace`: conservative source-span normalization into supervised tactic JSONL, with exclusion stats.
- `data trace-corpus`: resumable staged native InfoTree extraction for Mathlib files.
- `data corpus`: resumable staged Mathlib replay extraction.
- `preprocess`: JSONL formatting, deterministic file-level partitioning, and label/scope filtering; writes a provenance `manifest.json`.
- `train`: optional causal LM LoRA SFT using Transformers and PEFT.
- `prove`: bounded best-first search using a static tactic list; pass a JSON array to preserve commas inside Lean tactics.
- `evaluate`: fixed-node/wall-time search evaluation of whole theorem headers, writes per-problem JSONL.
- `evaluate-tactics`: held-out tactic-prediction comparison of base and LoRA on the same sample.
- `interact`: step through a proof in a Lean-checked CLI session, with optional model suggestions.
- `report`: summarizes result files under a directory.

### Interactive proof stepping

`interact` opens a session where every typed tactic is sent to Lean immediately. The prompt shows the current goals and the exact Lean error when a tactic is rejected; a proof is called verified only after the final kernel and axiom check.

```bash
python -m neuralproof.cli interact --file lean/NeuralProof/Samples.lean
python -m neuralproof.cli interact \
  --benchmark data/benchmarks/mathlib-test-50.jsonl \
  --theorem-id bench_np_bench_AlgCat_inv_hom_apply \
  --adapter experiments/mathlib-info-tree-lora-200-1epoch-canonical \
  --revision 4e53f736cbb20a9a0f56b4c4bf378d9f306ff915
```

Commands: `:goals`, `:suggest [n]`, `:search`, `:undo`, `:verify`, `:save [path]`, `:reset`, `:help`, `:quit`. Suggestions are displayed but never applied automatically, and `:search` runs bounded best-first search from the current state. A saved proof gets a `.json` sidecar marked `human_in_the_loop: true`, so an interactive proof is never counted as an autonomous benchmark result.

The static predictor is a testing baseline, not a language model. `neuralproof.models.predictor.load_hf_predictor` loads an HF base model or adapter; pass `--model-id`, `--adapter`, and an immutable `--revision` to `prove`/`evaluate` when available. A completion is scanned for the first line that is not an echo of the prompt, and an empty candidate is dropped rather than sent to Lean, so a model that answered nothing is not recorded as a model error. Search priority can be varied with `--priority bfs`, deduplication can be disabled with `--no-deduplicate`, and width/node limits expose small search ablations. No result should be labeled a base-vs-LoRA comparison until the same held-out set and budget have been executed with both weights.

`evaluate` proves whole theorems and therefore needs a `theorem` header per row; a mined InfoTree row carries a goal state instead and is rejected with a message pointing at `evaluate-tactics`.

### Lemma pre-filter (opt-in)

`prove` and `evaluate` accept `--filter-invalid-lemmas`, which refuses a candidate before it reaches Lean when it names an identifier absent from both the pinned Mathlib name index and the current context/goal state. It is **off by default**; existing runs are unchanged. The filter is a budget heuristic, not a correctness check: a name can exist and still not apply, so Lean remains the acceptance authority for every tactic that is tried.

The index is generated from the pinned environment, not maintained by hand:

```bash
python scripts/build_lemma_index.py        # writes data/lemma_index.json.gz + .meta.json
python scripts/check_lemma_filter.py --limit 342
```

`data/lemma_index.meta.json` records the Mathlib revision, Lean toolchain, dump hash, command, row counts, and output SHA-256. The index contains every constant name printed by Lean plus each name's last component, so an unqualified reference such as `range_eq_Ico` can resolve to `Finset.range_eq_Ico`. Indexing last components deliberately accepts some namespaces that would not elaborate; that only costs a Lean call, whereas dropping a name would produce a false reject. The held-out source tactics in the 342-row diagnostic are all accepted, while 62 of the 342 one-epoch LoRA predictions are refused and none of the 21 correct predictions is lost. Those numbers measure filter plumbing; they are not a proof-solving result.

## Soundness and current limits

The Lean client starts a fresh compiler process per tactic, replays the complete prefix, and asks Lean to print goals. This isolates candidate failures but costs seconds per cold invocation; it is not a persistent REPL. A tactic transition that closes the goal is accepted only after the reconstructed placeholder-free declaration compiles. `sorry` and `admit` are rejected by the final verifier. Multiple goals can be replayed, but state identity is currently the tactic prefix, not semantic environment equivalence; deduplication by printed goals is deliberately not used.

This MVP checks for unexpected axioms (allowing Lean's standard foundational `propext`, `Classical.choice`, and `Quot.sound`), but does not yet handle arbitrary syntax in supervised replay extraction, provide retrieval, compute pass@10, or measure GPU usage. The staged replay corpus contains 25 verified examples from 11 files, but its validation/test contain only 1 and 2 examples and are far too small for reliable claims. The checked-in one-row Mathlib pilot and three additional Mathlib-backed local smoke examples exercise tactic replay. This is not a benchmark. Remaining gaps are recorded in `docs/methodology.md` and `experiments/log.md`.

The 200-file InfoTree corpus is the source of the held-out tactic metric. It holds 6,221 mined transitions, of which 246 (4.0 %) are not tactics at all — the `by` of a declaration header, the `where` of a structure instance, a term brace, a placeholder — and are excluded from both training and scoring. The remaining 5,975 rows are split 4,789 / 773 / 413 by source file. Its contexts are reconstructed from source imports and active directives and have *not* been independently replayed, so its rows are next-tactic supervision, not proof certificates.

The first recorded held-out comparison of base vs LoRA reported 0/50 exact matches. That number was a harness artifact, not a model result: the prompt ended with a blank line, the model mirrored that blank line, and the harness read the model's first line as the tactic — so it recorded the model's silence as a wrong answer. With the canonical prompt and an echo-aware completion boundary, the same comparison still reports 0/50 on that small sample, but the run now records *how* each prediction failed (22 of 50 base and 2 of 50 LoRA completions contained no tactic at all; the rest were wrong tactics). A full-epoch LoRA (3976 proof-scope rows, 1 epoch) trained on the corrected pipeline achieved 21/342 exact matches (6.14%, Wilson 95% CI [0.0405, 0.0920]) on the full eligible held-out set (342 of 446 test rows; 33 excluded as non-tactic targets, 71 excluded as focus-scope). The base model was 0/342 (0.0%) with 157 silent predictions; the adapter produced 0 silent predictions. This is a tactic-prediction metric (exact string match of single-line source tactics), not a proof-solving rate. Neither the numbers nor the sample support general claims; see `experiments/log.md`.
