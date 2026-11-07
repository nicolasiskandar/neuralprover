# NeuralProof: Resource-Bounded Neural Tactic Prediction and Search

## Abstract

This draft proposes a controlled study of LoRA-based Lean tactic prediction combined with bounded best-first search. The implementation now provides a compiler-backed Lean 4 and pinned Mathlib pilot, plus a CPU training and inference smoke run. Broad Mathlib extraction and comparative evaluation remain incomplete; therefore, no neural efficacy result is claimed.

## Research question

Can LoRA tactic prediction and best-first search solve more Lean theorems than simpler baselines under fixed inference and verification budgets? A secondary question concerns search-state deduplication and prioritization.

## Related work

LeanDojo provides programmatic Lean interaction and data extraction, and ReProver studies retrieval-augmented proof generation. LoRA provides parameter-efficient model adaptation. These are foundations; this project would need to establish its contribution through controlled budget-matched search experiments.

## Methodology

The intended design extracts proof-state/tactic pairs, splits by source module, fine-tunes a configurable causal LM with PEFT LoRA, and runs greedy or bounded best-first inference. Every candidate transition and final proof is checked by Lean. Planned metrics include pass@1/10, verified theorem count, time, tactic calls, expanded nodes, model tokens, and failure rates.

## Current results

On a held-out, kernel-prevalidated 50-theorem Mathlib benchmark (`data/benchmarks/mathlib-test-50.jsonl`, stratified into 25 single-step and 25 multi-step proofs across 14 files), budget-matched best-first search (`max_nodes=20`, `width=4`, `timeout=30s`) yielded:
- **Zero-shot base model** (`SmolLM2-135M`): 0/50 solved (0.0%, Wilson 95% [0.0%, 7.1%]).
- **1-epoch canonical LoRA**: 6/50 solved (12.0%, Wilson 95% [5.6%, 23.8%], mean solve time 8.7s).
- **LoRA with Lemma Filtering**: 7/50 solved (14.0%, Wilson 95% [7.0%, 26.2%], mean solve time 6.7s, 44 unknown-lemma candidates pruned).
- **Static heuristic baseline** (`rfl`, `simp`, `assumption`, `exact True.intro`): 7/50 solved (14.0%, Wilson 95% [7.0%, 26.2%], mean solve time 5.3s).

All 7 solved theorems were single-step proofs (28.0% of single-step). Zero multi-step proofs were solved (0/25). Lemma filtering successfully pruned 44 hallucinated lemma calls and reduced invalid tactic executions by 14.2% (from 212 to 182), lowering solve latency without sacrificing theorem coverage. Detailed metrics are recorded in `experiments/benchmark-50/report.md` and `experiments/log.md`.

## Limitations and threats to validity

The current source parser excludes common Lean syntax. The replay backend incurs high subprocess overhead and goal-state parsing is intentionally minimal. The pilot sample cannot support generalization claims. No GPU is available. The five-example LoRA smoke run had no held-out set and generated unusable tactics on its one attempted theorem. A larger Mathlib dataset needs leakage audits by files, declarations, and proof similarity.

## Reproducibility

See `docs/reproducibility.md` and `experiments/log.md`. Re-run the Lean smoke checks with `pytest` (or `pytest -m lean` for the cases that invoke the toolchain).

## References

- Yang et al. “LeanDojo: Theorem Proving with Retrieval-Augmented Language Models.” NeurIPS 2023. https://arxiv.org/abs/2306.15626
- ReProver implementation and model documentation: https://github.com/lean-dojo/ReProver
- Lean 4 documentation and machine-interaction REPL entry: https://lean-lang.org/lean4/doc
- Mathlib4 repository and Apache-2.0 license: https://github.com/leanprover-community/mathlib4
- Hugging Face PEFT LoRA documentation: https://huggingface.co/docs/peft/en/package_reference/lora
