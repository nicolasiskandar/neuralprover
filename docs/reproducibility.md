# Reproducibility

Lean is pinned at `leanprover/lean4:v4.35.0`. Mathlib is pinned at commit `56a005855ea17e0b0958f73ec801ae140b0a1679`; `lean/lake-manifest.json` locks its transitive dependencies. Set up with `cd lean && lake update && lake build`. Core Python runtime code uses the standard library; the optional retrieval path adds NumPy, torch, and transformers, and the training path adds torch, transformers, PEFT, and datasets, all version-pinned or bounded in `pyproject.toml`. Installation/model download requires network or a prepopulated cache. For CPU-only training, use the official PyTorch CPU wheel index and explicitly select `torch==2.6.0+cpu` as shown in the README.

Record command, git revision, Lean version, Python version, model ID and immutable revision, dataset hash, random seed, inference settings, search limits, and hardware in each experiment directory. Do not use the smoke sample to make performance claims. Current test invocation: `pytest` (the `lean` marker selects the cases that invoke the toolchain; `pytest -m "not lean"` runs the rest).

The current clean one-row Mathlib pilot JSONL SHA-256 is `7339b56e1477f54367f964cb31d54f1f72f50cb7db081eb1e7820dc4f31800bd`; the Lake manifest SHA-256 is `4edf9b1976ae48624f000401516854e32bab61d2071a9dd3784740f1737ed776`. The 200-file clean corpus selection hash is in `data/mathlib-200/manifest.json`; the rows, per-file stats, and prompt-formatted split files should be archived together. A CPU smoke run used Python 3.11.17, PyTorch 2.6.0+cpu, Transformers 4.49.0, PEFT 0.14.0, seed 17, and the immutable SmolLM2-135M revision `4e53f736cbb20a9a0f56b4c4bf378d9f306ff915`. An earlier five-row pilot training run is superseded because its `import Mathlib` context may have exposed target declarations; see the experiment log for the clean corpus training run and its limitations. Historical trainer artifacts remain under `experiments/smol-lora-smoke/`. The model weights are cached outside the repository; in this environment the cache is `/home/nicolas/.cache/huggingface`, which is selected with `HF_HOME=/home/nicolas/.cache/huggingface` (and `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` when the machine has no network).

The native InfoTree extraction smoke command is:

```bash
python -m neuralproof.cli data trace \
  --file lean/.lake/packages/mathlib/Mathlib/Algebra/AddConstMap/Basic.lean \
  --output data/traces/addconstmap-basic.json
```

It records raw overlapping InfoTree nodes, not normalized tactic trajectories. The staged replay corpus is resumable with `python -m neuralproof.cli data corpus --files 200 --per-file 5 --output data/mathlib-200`; its `manifest.json` pins the selection by hash and `summary.json` reports actual completed counts. Keep `examples.jsonl`, `file_stats.jsonl`, and the manifest together when archiving a corpus run.

To extract and preprocess native Mathlib InfoTree states, run
`python -m neuralproof.cli data trace-corpus --files 200 --output data/mathlib-info-tree-200`, then `python -m neuralproof.cli preprocess --input data/mathlib-info-tree-200/examples.jsonl --output data/mathlib-info-tree-200/processed --include-unvalidated`. These normalized examples are observed during whole-file Lean elaboration, but their reconstructed per-example contexts have not been independently replayed, so the rows are stamped `validation_status: unreplayed` and are not proof certificates.

Preprocessing excludes rows whose target is not a tactic and records the count in `manifest.json` (`excluded_non_tactic_targets`), records the scope of every row (`goal_scope_counts`), and pins the code revision and diff hash it was produced from. The diff hash is taken before the manifest is written and the manifest is itself a tracked file, so it identifies the code and the inputs that produced the rows, not a tree that contains the manifest; the manifest says so in its own `caveats`. Regenerate the processed artifacts after changing the prompt or the label rule; a processed set whose manifest predates the change describes a different dataset than the one on disk.

A full CPU epoch over the 3,976 proof-scope training rows takes roughly 80 minutes at about 1.1 s per step. `--max-steps` is the step budget: it defaults to `-1`, which trains for the full number of epochs, and `0` is rejected because `TrainingArguments` would end the run after its first step.

```bash
neuralproof train \
  --data data/mathlib-info-tree-200/processed/train.jsonl \
  --model HuggingFaceTB/SmolLM2-135M \
  --revision 4e53f736cbb20a9a0f56b4c4bf378d9f306ff915 \
  --output experiments/mathlib-info-tree-lora-200-1epoch-canonical \
  --epochs 1 --seed 17 --goal-scope proof
```

The held-out tactic metric command is:

```bash
neuralproof evaluate-tactics \
  --data data/mathlib-info-tree-200/examples.jsonl \
  --adapter experiments/mathlib-info-tree-lora-200-1epoch-canonical \
  --revision 4e53f736cbb20a9a0f56b4c4bf378d9f306ff915 \
  --limit 342 --seed neuralproof-mathlib-info-tree-v1 \
  --output experiments/mathlib-info-tree-lora-200-1epoch-canonical/tactic-eval-full-heldout.json
```

342 is the number of eligible rows (446 held out, minus 33 non-tactic targets and 71 focus-scope rows), so `--limit 342` scores the whole eligible set rather than a sample; a smaller limit scores a deterministic pseudo-random subset chosen by the seed.

The result records `heldout_examples`, `excluded_non_tactic_targets`, `excluded_focus_scope`, `sample_size`, and, per model, `exact_matches` alongside `silent_predictions`. Report the silent count with the accuracy: a run in which the model answered nothing and a run in which the model answered wrongly are different findings.

The lemma-name index is a generated artifact pinned to the same Mathlib revision:

```bash
python scripts/build_lemma_index.py
python scripts/check_lemma_filter.py --limit 342 --output experiments/lemma-filter-report.json
```

The builder runs `lake env lean --run NeuralProof/DumpDeclarations.lean` from `lean/`, sorts/deduplicates the constant names, adds each name's last component, and writes `data/lemma_index.json.gz`. `data/lemma_index.meta.json` records the dump command, Mathlib revision, Lean toolchain, constant and basename counts, dump/output SHA-256, code revision, and whether the tree was dirty. To rebuild from a captured dump without invoking Lean, pass `--from-file <dump>`. The index is a name set, not applicability evidence; the opt-in `--filter-invalid-lemmas` flag on `prove`/`evaluate` still sends every accepted candidate to Lean. `scripts/check_lemma_filter.py` exits non-zero when the number of held-out source tactics rejected by the filter exceeds `--max-false-rejects` (default 0); the current index rejects 0/342 targets and 62/342 adapter predictions, losing none of the 21 correct predictions.

Search artifacts record `rejected_unknown_lemmas` next to `tactic_calls`, `invalid_tactics`, and `timeouts`, so a filtered run cannot be mistaken for an unfiltered one. The filter is off by default; a run that asks for it and cannot find the index fails rather than silently running unfiltered.

The retrieval-feasibility study uses a separate theorem-statement corpus and an optional dense index. Rebuild them with:

```bash
python scripts/build_lemma_statements.py \
  --kinds theorem \
  --output data/lemma_statements.jsonl.gz \
  --meta data/lemma_statements.meta.json
python scripts/build_lemma_embeddings.py \
  --output data/cache/lemma-embeddings/all-MiniLM-L6-v2.npy
python scripts/evaluate_retrieval.py \
  --corpus data/lemma_statements.jsonl.gz \
  --embeddings data/cache/lemma-embeddings/all-MiniLM-L6-v2.npy \
  --output-dir experiments/retrieval-feasibility
```

Without `--from-file`, the builder runs the two Lean dumpers from `lean/`: `lake env lean --run NeuralProof/DumpStatements.lean --import Mathlib --kinds theorem` and `lake env lean --run NeuralProof/DumpModules.lean --import Mathlib`. `data/lemma_statements.meta.json` records both commands, the Mathlib revision, Lean toolchain, input/output SHA-256, filter counts, and the working-tree state. To rebuild from captured dumps without importing Mathlib again, pass `--from-file <statements.jsonl>` and `--modules-file <modules.tsv>`.

The embedding builder is resumable and writes one normalized float32 row per corpus row. Its cache and metadata stay under ignored `data/cache/lemma-embeddings/`; metadata records the model, immutable revision, pooling, max length, corpus SHA, matrix SHA, and build command. The evaluator fails if the corpus digest, row count, matrix digest, encoder dimension, or model settings disagree with the cache. The dense path needs the optional dependencies from `pip install -e '.[retrieval]'`; the evaluator also uses the pure lexical path without them, but the dense and hybrid sections require NumPy, torch, and transformers.

The corpus and embeddings are retrieval input: types are delaborated, not re-elaborated, and a retrieval hit is not a verified lemma application. See `experiments/retrieval-feasibility/README.md` for the measurement and its limitations.
