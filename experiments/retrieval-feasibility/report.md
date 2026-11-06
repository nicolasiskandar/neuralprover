# Retrieval Feasibility

Lexical BM25 retrieval over Mathlib theorem statements, plus dense and
hybrid sections when a cached embedding matrix is supplied. Recall is a
diagnostic; a retrieved name is not a verified lemma application.

## Coverage

- Eval rows: 342
- Applicable rows (at least one in-corpus global target lemma): 84 (24.6%)
- Applicability: {'in_corpus': 84, 'local_only': 52, 'no_reference': 205, 'out_of_corpus_only': 1}
- Global target references: 141; local references: 88 (local references are not retrieval failures)
- Out-of-corpus global references (not retrieval failures): {'ULift.up_bijective.comp': 1}

## Recall by query (relaxed name match)

| index | query | @1 | @5 | @10 | @20 |
| :-- | :-- | --: | --: | --: | --: |
| name only | goal target | 0.0% | 4.8% | 9.5% | 10.7% |
| name only | full goal state | 2.4% | 3.6% | 3.6% | 8.3% |
| name only | context + goal | 1.2% | 6.0% | 10.7% | 11.9% |
| name + type | goal target | 4.8% | 28.6% | 32.1% | 34.5% |
| name + type | full goal state | 7.1% | 33.3% | 33.3% | 33.3% |
| name + type | context + goal | 6.0% | 25.0% | 29.8% | 32.1% |

## Strict name matching (row-level)

| index | query | @1 | @5 | @10 | @20 |
| :-- | :-- | --: | --: | --: | --: |
| name only | goal target | 0.0% | 4.8% | 8.3% | 9.5% |
| name only | full goal state | 1.2% | 2.4% | 2.4% | 8.3% |
| name only | context + goal | 1.2% | 6.0% | 10.7% | 11.9% |
| name + type | goal target | 4.8% | 28.6% | 32.1% | 32.1% |
| name + type | full goal state | 6.0% | 32.1% | 32.1% | 32.1% |
| name + type | context + goal | 4.8% | 23.8% | 28.6% | 31.0% |

## Same-module exclusion (leakage control, goal target)

Removes every declaration defined in the target's source module.

| index | @1 | @5 | @10 | @20 |
| :-- | --: | --: | --: | --: |
| name only | 0.0% | 3.6% | 6.0% | 7.1% |
| name + type | 2.4% | 6.0% | 7.1% | 9.5% |

## By tactic family (name + type, goal target)

| family | rows | @1 | @5 | @10 | @20 |
| :-- | --: | --: | --: | --: | --: |
| `apply` | 7 | 0.0% | 0.0% | 0.0% | 0.0% |
| `conv` | 1 | 0.0% | 0.0% | 0.0% | 0.0% |
| `conv_lhs` | 1 | 0.0% | 0.0% | 0.0% | 0.0% |
| `exact` | 2 | 0.0% | 0.0% | 0.0% | 0.0% |
| `obtain` | 2 | 0.0% | 0.0% | 0.0% | 0.0% |
| `refine` | 4 | 0.0% | 0.0% | 0.0% | 0.0% |
| `rw` | 23 | 13.0% | 13.0% | 17.4% | 26.1% |
| `simp` | 21 | 0.0% | 9.5% | 9.5% | 9.5% |
| `simp_rw` | 4 | 0.0% | 50.0% | 50.0% | 50.0% |
| `simpa` | 19 | 5.3% | 89.5% | 100.0% | 100.0% |

## Reference-level recall (goal target)

| index | @1 | @5 | @10 | @20 |
| :-- | --: | --: | --: | --: |
| name only | 0.0% | 2.9% | 5.7% | 6.4% |
| name + type | 2.9% | 17.1% | 19.3% | 20.7% |

## Dense and hybrid retrieval

- Encoder: `sentence-transformers/all-MiniLM-L6-v2` at revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` (mean pooling, max length 128, embedding SHA-256 `9628016f26e67be11d4ff5b32cc3bdfcea6ca88aa767cb4799574e81fb49f405`).
- Hybrid: reciprocal rank fusion of BM25 name + type and dense, depth 50, k=60.0, equal weights.
- The model, revision, pooling, depth and k were fixed before
  evaluation; nothing was tuned on the held-out targets.

| retriever | query | @1 | @5 | @10 | @20 |
| :-- | :-- | --: | --: | --: | --: |
| dense | goal target | 2.4% | 11.9% | 14.3% | 15.5% |
| dense | full goal state | 7.1% | 31.0% | 31.0% | 31.0% |
| dense | context + goal | 13.1% | 22.6% | 26.2% | 27.4% |
| hybrid | goal target | 3.6% | 21.4% | 32.1% | 36.9% |
| hybrid | full goal state | 16.7% | 31.0% | 33.3% | 34.5% |
| hybrid | context + goal | 15.5% | 27.4% | 29.8% | 29.8% |

### Dense and hybrid same-module exclusion (goal target)

| retriever | @1 | @5 | @10 | @20 |
| :-- | --: | --: | --: | --: |
| dense | 1.2% | 2.4% | 3.6% | 6.0% |
| hybrid | 1.2% | 6.0% | 8.3% | 13.1% |

### Dense and hybrid by tactic family (goal target)

| retriever | family | rows | @1 | @5 | @10 | @20 |
| :-- | :-- | --: | --: | --: | --: | --: |
| dense | `apply` | 7 | 0.0% | 0.0% | 0.0% | 0.0% |
| dense | `conv` | 1 | 0.0% | 0.0% | 0.0% | 0.0% |
| dense | `conv_lhs` | 1 | 0.0% | 0.0% | 0.0% | 0.0% |
| dense | `exact` | 2 | 0.0% | 0.0% | 0.0% | 0.0% |
| dense | `obtain` | 2 | 0.0% | 0.0% | 0.0% | 0.0% |
| dense | `refine` | 4 | 0.0% | 0.0% | 0.0% | 0.0% |
| dense | `rw` | 23 | 0.0% | 0.0% | 0.0% | 0.0% |
| dense | `simp` | 21 | 4.8% | 9.5% | 14.3% | 14.3% |
| dense | `simp_rw` | 4 | 0.0% | 0.0% | 0.0% | 0.0% |
| dense | `simpa` | 19 | 5.3% | 42.1% | 47.4% | 52.6% |
| hybrid | `apply` | 7 | 0.0% | 0.0% | 0.0% | 0.0% |
| hybrid | `conv` | 1 | 0.0% | 0.0% | 0.0% | 0.0% |
| hybrid | `conv_lhs` | 1 | 0.0% | 0.0% | 0.0% | 0.0% |
| hybrid | `exact` | 2 | 0.0% | 0.0% | 0.0% | 0.0% |
| hybrid | `obtain` | 2 | 0.0% | 0.0% | 0.0% | 0.0% |
| hybrid | `refine` | 4 | 0.0% | 0.0% | 0.0% | 0.0% |
| hybrid | `rw` | 23 | 4.3% | 13.0% | 21.7% | 26.1% |
| hybrid | `simp` | 21 | 4.8% | 9.5% | 9.5% | 23.8% |
| hybrid | `simp_rw` | 4 | 0.0% | 0.0% | 50.0% | 50.0% |
| hybrid | `simpa` | 19 | 5.3% | 68.4% | 94.7% | 94.7% |

## Notes

- The denominator is the applicable rows; local-only and no-reference
  rows are not retrieval failures.
- Target references that are not theorems in the corpus (definitions,
  constructors, syntax) are listed in `report.json` and are not counted
  as retrieval failures.
- ``same_module_excluded`` is a conservative leakage control. It is too
  strict because the target lemma often lives in the same source module.
- A retrieval hit is not a verified lemma application; Lean is the
  authority for proof acceptance.

