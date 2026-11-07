# 50-Theorem Proof-Search Evaluation Campaign

## Overview

- **Benchmark**: 50 held-out Mathlib theorems ([`data/benchmarks/mathlib-test-50.jsonl`](../../data/benchmarks/mathlib-test-50.jsonl))
- **Search Budget**: `max_nodes=20`, `width=4`, `timeout=30.0s`
- **Date**: 2026-11-07 18:04:37 UTC

## Summary Results

| Configuration | Attempted | Solved | Solve Rate (Wilson 95%) | Mean Nodes | Mean Calls | Invalid Tactics | Filtered Lemmas | Mean Solve (s) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **static** | 50 | 7 | 14.0% [7.0%, 26.2%] | 1.2 | 4.6 | 212 | 0 | 5.3 |
| **base** | 50 | 0 | 0.0% [0.0%, 7.1%] | 1.0 | 2.3 | 117 | 0 | — |
| **lora** | 50 | 6 | 12.0% [5.6%, 23.8%] | 1.2 | 4.7 | 212 | 0 | 8.7 |
| **lora_filtered** | 50 | 7 | 14.0% [7.0%, 26.2%] | 1.4 | 4.3 | 182 | 44 | 6.7 |

## Stratified Performance by Proof Depth

| Configuration | Single-Step Solved (of 25) | Multi-Step Solved (of 25) | Overall Solved (of 50) |
| :--- | :---: | :---: | :---: |
| **static** | 7 / 25 (28.0%) | 0 / 25 (0.0%) | 7 / 50 (14.0%) |
| **base** | 0 / 25 (0.0%) | 0 / 25 (0.0%) | 0 / 50 (0.0%) |
| **lora** | 6 / 25 (24.0%) | 0 / 25 (0.0%) | 6 / 50 (12.0%) |
| **lora_filtered** | 7 / 25 (28.0%) | 0 / 25 (0.0%) | 7 / 50 (14.0%) |

## Solved Theorems Detail

- **`AlgCat.inv_hom_apply`** (`Mathlib/Algebra/Category/AlgCat/Basic.lean`)
  - Depth: 1, Solved by: `static`, `lora_filtered`
- **`CommAlgCat.comp_apply`** (`Mathlib/Algebra/Category/CommAlgCat/Basic.lean`)
  - Depth: 1, Solved by: `static`, `lora`, `lora_filtered`
- **`CommAlgCat.inv_hom_apply`** (`Mathlib/Algebra/Category/CommAlgCat/Basic.lean`)
  - Depth: 1, Solved by: `static`, `lora`, `lora_filtered`
- **`LinearMap.comp_id_semiModuleCat`** (`Mathlib/Algebra/Category/ModuleCat/Semi.lean`)
  - Depth: 1, Solved by: `static`, `lora`, `lora_filtered`
- **`LinearMap.id_semiModuleCat_comp`** (`Mathlib/Algebra/Category/ModuleCat/Semi.lean`)
  - Depth: 1, Solved by: `static`, `lora`, `lora_filtered`
- **`SemimoduleCat.hom_inv_apply`** (`Mathlib/Algebra/Category/ModuleCat/Semi.lean`)
  - Depth: 1, Solved by: `static`, `lora`, `lora_filtered`
- **`SemimoduleCat.inv_hom_apply`** (`Mathlib/Algebra/Category/ModuleCat/Semi.lean`)
  - Depth: 1, Solved by: `static`, `lora`, `lora_filtered`
