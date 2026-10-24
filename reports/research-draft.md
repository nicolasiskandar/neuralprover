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

The pilot contains two local Lean core examples, three Mathlib-backed local replay examples, and five source-mined trajectories from three pinned Mathlib files. An oracle static list of the three Nat tactics verified 3/3 in width-three/20-node search (one node expanded and two tactic calls per theorem on average; Wilson 95% interval [0.438, 1.000]). Correct tactics were supplied directly, so this is plumbing evidence only; the other two source-mined examples were verified during extraction but not included in that search run. Seventeen unit tests pass, including cross-module Mathlib extraction and verification. No pretrained-model inference, LoRA training, pass@10 result, or comparative experiment has run.

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
