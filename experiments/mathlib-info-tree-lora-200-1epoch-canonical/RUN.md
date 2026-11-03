# One-epoch LoRA run — canonical artifact index

This directory holds the generated adapter and the artifacts used by
`docs/methodology.md` and the 2026-10-24 entry in `experiments/log.md`. The
adapter weights and tokenizer copy are intentionally gitignored; the small
evaluation and analysis artifacts are tracked.

## Run

```bash
python -m neuralproof.cli train \
  --data data/mathlib-info-tree-200/processed/train.jsonl \
  --model HuggingFaceTB/SmolLM2-135M \
  --revision 4e53f736cbb20a9a0f56b4c4bf378d9f306ff915 \
  --output experiments/mathlib-info-tree-lora-200-1epoch-canonical \
  --epochs 1 --seed 17 --goal-scope proof
```

- Full epoch: `global_step` 3976, `epoch` 1.0, `--max-steps -1`.
- Training used the canonical prompt and 3,976 proof-scope rows.
- `adapter_model.safetensors` SHA-256:
  `346854e4fbe9ba7cf974f228936c66ad9ba680b6cf392ab0055eb422fd5dbceb`.
- Input artifacts (local, gitignored):
  `data/mathlib-info-tree-200/processed/train.jsonl` SHA-256
  `473852b9b1547aaaec93f4a78254b22ae3d15d690eaf503f28b8bf9378210b6d`;
  `data/mathlib-info-tree-200/examples.jsonl` SHA-256
  `b1a3a776d6eead9bcca2fcd4677613ae4bf67ec227e42b85fda3518641580cd6`.

## Held-out tactic prediction

```bash
python -m neuralproof.cli evaluate-tactics \
  --data data/mathlib-info-tree-200/examples.jsonl \
  --adapter experiments/mathlib-info-tree-lora-200-1epoch-canonical \
  --revision 4e53f736cbb20a9a0f56b4c4bf378d9f306ff915 \
  --limit 342 --seed neuralproof-mathlib-info-tree-v1 \
  --output experiments/mathlib-info-tree-lora-200-1epoch-canonical/tactic-eval-full-heldout.json
```

`tactic-eval-full-heldout.json` (SHA-256
`149e0b85e5cbcea5e6edc1431913ae21d2446bb3dd82da8119fd9abfc20cc70a`) records
446 held-out rows, 342 eligible after exclusions, base 0/342 exact matches
(157 silent), and LoRA 21/342 exact matches (0 silent). `error_analysis.md` and
`lemma_analysis.md` are diagnostics over that file.

Exact string match of a single-line source tactic is not proof success; the
contexts have not been independently replayed. No theorem-solving claim follows
from these numbers. `lemma_analysis.md` was regenerated with the current shared
extractor (`neuralproof.lemmas.extract_symbol_heads`); it now loads 2,044 unique
training lemmas and points to the retrieval-feasibility study rather than
recommending retrieval as if it had already been validated.
