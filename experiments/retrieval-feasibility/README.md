# Retrieval feasibility

Can Mathlib lemma retrieval supply the lemma arguments that the fine-tuned
model gets wrong? This study measures that question on the existing held-out
targets before any retrieval is added to prompts, decoding, or training.

Recall is a diagnostic. A retrieved name is not a verified lemma application:
the type may not match, implicit arguments may not be inferable, the rewrite
may go the wrong way, or a side condition may be unprovable. Lean remains the
authority for proof acceptance, and no number in this directory is a
proof-solving result.

## Protocol

- **Rows.** The 342 proof-scope held-out source tactics from
  `experiments/mathlib-info-tree-lora-200-1epoch-canonical/tactic-eval-full-heldout.json`,
  joined to `data/mathlib-info-tree-200/examples.jsonl` for context and goal.
- **Extraction.** The same `neuralproof.lemmas.extract_symbol_heads` used by
  the pre-filter, so this report cannot drift from what search sees.
- **Local vs global.** A reference that appears in the row's context or goal
  state is *local* and is not a retrieval failure. A reference that resolves to
  the pinned Mathlib name index but not to the statement corpus is
  *out-of-corpus* (definitions, constructors, syntax) and is also not a
  retrieval failure.
- **Gold.** A global target reference that is a theorem in the statement
  corpus. Rows with at least one such reference are the applicability
  denominator.
- **Queries.** The goal target after `⊢` (primary), the full goal state, and
  context + goal (ablations). Inaccessible-name markers (`✝`) and `case` labels
  are stripped before indexing or querying.
- **Indexes.** BM25 over the lemma name alone, and over name + pretty-printed
  type. Both are deterministic and built only from the corpus; no held-out
  target tactic is used to build or tune them.
- **Matching.** Relaxed matching accepts a qualified suffix or the same last
  component; strict matching requires a qualified-suffix relation. Reference
  level recall counts how many gold references appear in the top *k*.
- **Leakage control.** `same_module_excluded` removes every declaration from
  the target's source module before ranking. This is conservative: the needed
  lemma often lives in the same module, so it understates realistic recall.

## Corpus

`data/lemma_statements.jsonl.gz` is generated from the pinned environment, not
from the held-out rows. It is not tracked: the gzip is 12.0 MB and 131 MB
uncompressed, and the metadata below plus the reproduction commands are enough
to rebuild and verify it.

| field | value |
| :-- | :-- |
| declarations in dump | 547,938 theorems |
| corpus rows | 361,832 theorems |
| dropped as compiler-internal | 186,106 |
| Mathlib revision | `56a005855ea17e0b0958f73ec801ae140b0a1679` |
| Lean toolchain | `leanprover/lean4:v4.35.0` |
| output SHA-256 | `a944016322fa5f0f9e4ec1a835505131bddab5b9ee1c7675c9e80d0400530f30` |
| gzip size | 12.0 MB |

Provenance is in `data/lemma_statements.meta.json`, including the two Lean
dump commands. Private and compiler-generated names (`match_*`, `recOn_*`,
`casesOn_*`, `brecOn_*`, `below_*`, `_flat_ctor_*`, `ctorIdx_*`, `_proof_*`)
are dropped. Equation lemmas are retained by default. Types are delaborated,
not re-elaborated, so the corpus is retrieval input only.

## Results

Applicability: **84/342 rows (24.6%)** have at least one in-corpus theorem
reference. The other 258 rows are 205 with no extracted reference, 52
local-only, and 1 out-of-corpus-only (`ULift.up_bijective.comp`). Across all
rows there are 141 global references and 88 local references.

Row-level recall over the 84 applicable rows:

| index | query | @1 | @5 | @10 | @20 |
| :-- | :-- | --: | --: | --: | --: |
| name only | goal target | 0.0% | 4.8% | 9.5% | 10.7% |
| name only | full goal state | 2.4% | 3.6% | 3.6% | 8.3% |
| name only | context + goal | 1.2% | 6.0% | 10.7% | 11.9% |
| name + type | goal target | 4.8% | 28.6% | 32.1% | **34.5%** |
| name + type | full goal state | 7.1% | 33.3% | 33.3% | 33.3% |
| name + type | context + goal | 6.0% | 25.0% | 29.8% | 32.1% |

Reference-level recall for name + type / goal target is 2.9% / 17.1% / 19.3% /
20.7% at 1/5/10/20. Strict name matching changes the name + type / goal target
@20 figure only from 34.5% to 32.1%.

Same-module exclusion (leakage control, goal target):

| index | @1 | @5 | @10 | @20 |
| :-- | --: | --: | --: | --: |
| name only | 0.0% | 3.6% | 6.0% | 7.1% |
| name + type | 2.4% | 6.0% | 7.1% | 9.5% |

By tactic family (name + type, goal target):

| family | rows | @1 | @5 | @10 | @20 |
| :-- | --: | --: | --: | --: | --: |
| `apply` | 7 | 0.0% | 0.0% | 0.0% | 0.0% |
| `exact` | 2 | 0.0% | 0.0% | 0.0% | 0.0% |
| `refine` | 4 | 0.0% | 0.0% | 0.0% | 0.0% |
| `obtain` | 2 | 0.0% | 0.0% | 0.0% | 0.0% |
| `rw` | 23 | 13.0% | 13.0% | 17.4% | 26.1% |
| `simp` | 21 | 0.0% | 9.5% | 9.5% | 9.5% |
| `simp_rw` | 4 | 0.0% | 50.0% | 50.0% | 50.0% |
| `simpa` | 19 | 5.3% | 89.5% | 100.0% | 100.0% |
| `conv` / `conv_lhs` | 2 | 0.0% | 0.0% | 0.0% | 0.0% |

## Interpretation

Lexical retrieval is **inadequate** as a drop-in source of lemma arguments.

- **Top-1 is unusable.** 4.8% of applicable rows have a gold lemma at rank 1;
  even at 20 candidates it is 34.5%. A search that tries 20 retrieved lemmas
  per goal pays a large Lean budget for a one-in-three chance of including the
  right name.
- **The aggregate is clustered.** The 84 applicable rows come from only 14
  source files. 18 of the 29 hits at 20 come from one file,
  `Mathlib/Algebra/BigOperators/ModEq.lean`, and only 8 files contribute any
  hit. The 100% `simpa` result is 17 near-duplicate `listSum`/`listProd`
  declarations from that one module, not general retrieval ability.
- **The families that need help are the ones retrieval misses.** `apply`,
  `exact`, `refine`, and `obtain` are at 0% at every cutoff. `rw` reaches 26.1%
  at 20, again concentrated in the same modules.
- **Same-module exclusion collapses recall to 9.5%.** Because the corpus is
  built from the whole library, near-duplicate declarations in the target's own
  module inflate the headline. A realistic future-proof evaluation needs a
  stronger temporal or duplicate control than "same module".
- **Statement text helps.** Name + type roughly triples name-only recall at 20
  (34.5% vs 10.7%), so the type is carrying real signal and should stay in any
  future index.
- **The goal target is the best query.** Full goal and context + goal do not
  beat it; adding context dilutes the terms that identify the lemma.
- **Coverage is the other ceiling.** Only 24.6% of held-out rows have an
  in-corpus theorem reference at all, so even perfect retrieval could affect at
  most a quarter of these rows.

## Decision

Do not integrate this lexical retriever into prompts, decoding, or training.
The conditional next step is a better retriever: embeddings or a hybrid
lexical + dense index, or a model reranker over the BM25 candidates, measured
on the same 84 applicable rows with the same local/out-of-corpus accounting and
a stronger leakage control. A two-stage "model predicts the skeleton,
retrieval fills the lemma" design remains a candidate, but only after retrieval
recall is materially better and candidate acceptance is measured by Lean, not
by name match.

## Reproduction

```bash
python scripts/build_lemma_statements.py \
  --kinds theorem \
  --output data/lemma_statements.jsonl.gz \
  --meta data/lemma_statements.meta.json
python scripts/evaluate_retrieval.py \
  --corpus data/lemma_statements.jsonl.gz \
  --output-dir experiments/retrieval-feasibility
pytest tests/test_retrieval.py tests/test_lemma_statements.py \
  tests/test_evaluate_retrieval.py
```

`scripts/build_lemma_statements.py` runs
`lake env lean --run NeuralProof/DumpStatements.lean --import Mathlib --kinds theorem`
and `lake env lean --run NeuralProof/DumpModules.lean --import Mathlib` from
`lean/` unless `--from-file` / `--modules-file` are supplied. The evaluation
takes about a minute on this machine and writes `report.json` and `report.md`.
`report.json` holds the per-row candidate lists and all ablation tables; this
README holds the interpretation.
