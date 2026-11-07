# Retrieval feasibility

Can Mathlib lemma retrieval supply the lemma arguments that the fine-tuned
model gets wrong? This study measures that question on the existing held-out
targets before any retrieval is added to prompts, decoding, or training.
Lexical BM25, dense sentence embeddings, and a reciprocal-rank-fusion hybrid
are compared on the same rows.

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
  type. A dense index over the same name + type documents, and a reciprocal
  rank fusion (RRF) of BM25 name + type and dense. All are built only from the
  corpus; no held-out target tactic is used to build or tune them.
- **Dense encoder.** `sentence-transformers/all-MiniLM-L6-v2` at revision
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, mean pooling, max length 128,
  L2-normalized float32. Similarity is a dot product. The encoder, revision,
  pooling, RRF depth 50, and RRF k=60 were fixed before evaluation; none was
  tuned on the held-out rows.
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

The dense index caches one 384-dimensional vector per corpus row under the
ignored `data/cache/lemma-embeddings/` directory. The matrix is 361,832 × 384
float32, SHA-256
`9628016f26e67be11d4ff5b32cc3bdfcea6ca88aa767cb4799574e81fb49f405`, and its
metadata records the model, revision, pooling, max length, corpus SHA, and
build command. The evaluator refuses a cache whose corpus digest, row count,
matrix digest, encoder dimension, or model settings do not match.

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

### Dense and hybrid

Dense retrieval uses the same name + type documents. Hybrid fuses BM25
name + type and dense with RRF (depth 50, k=60, equal weights). Row-level
recall over the same 84 applicable rows:

| retriever | query | @1 | @5 | @10 | @20 |
| :-- | :-- | --: | --: | --: | --: |
| dense | goal target | 2.4% | 11.9% | 14.3% | 15.5% |
| dense | full goal state | 7.1% | 31.0% | 31.0% | 31.0% |
| dense | context + goal | 13.1% | 22.6% | 26.2% | 27.4% |
| hybrid | goal target | 3.6% | 21.4% | 32.1% | **36.9%** |
| hybrid | full goal state | **16.7%** | 31.0% | 33.3% | 34.5% |
| hybrid | context + goal | 15.5% | 27.4% | 29.8% | 29.8% |

Dense alone is worse than lexical BM25 on the primary goal-target query at
every cutoff (15.5% vs 34.5% at 20). Hybrid adds two rows at 20 (31/84 vs
29/84) but loses early precision: @1 falls from 4.8% to 3.6% and @5 from 28.6%
to 21.4%, while @10 is unchanged at 32.1%. Reference-level hybrid recall is
2.1% / 12.9% / 19.3% / 22.9%, versus 2.9% / 17.1% / 19.3% / 20.7% for lexical
name + type.

Same-module exclusion (goal target):

| retriever | @1 | @5 | @10 | @20 |
| :-- | --: | --: | --: | --: |
| dense | 1.2% | 2.4% | 3.6% | 6.0% |
| hybrid | 1.2% | 6.0% | 8.3% | 13.1% |

The hybrid gains 2 rows at 20 over lexical same-module exclusion (13.1% vs
9.5%), but remains low. By tactic family, hybrid reaches 26.1% at 20 for `rw`
(the same as lexical), 23.8% for `simp` (up from 9.5%), 50.0% for `simp_rw`,
and 94.7% for `simpa` (down from 100%). `apply`, `exact`, `refine`, and
`obtain` remain at 0% at every cutoff, and dense alone is 0% for `rw`.

The hit set is still clustered. Hybrid has 31 hits at 20 from 8 source files;
19 of them are in `Mathlib/Algebra/BigOperators/ModEq.lean`. It gains three
rows over lexical and loses one, and two of the three gains are additional
`ModEq` declarations. Dense has 13 hits, 9 of them in the same module.

## Interpretation

Lexical, dense, and hybrid retrieval are all **inadequate** as a drop-in source
of lemma arguments. Dense alone does not improve candidate recall over BM25;
hybrid buys a small top-20 gain at the cost of early precision.

- **Top-1 is unusable.** Lexical name + type has 4.8% of applicable rows with
  a gold lemma at rank 1; hybrid has 3.6% and dense 2.4%. Even at 20 candidates
  the best retriever is hybrid at 36.9%. A search that tries 20 retrieved
  lemmas per goal pays a large Lean budget for a one-in-three chance of
  including the right name.
- **Dense is weaker than lexical on statements.** MiniLM embeddings over
  name + type reach 15.5% at 20 on the goal target, versus 34.5% for BM25.
  Mathlib statement syntax is dominated by generic typeclass and binder text,
  so the embedding similarity is not identifying the needed declaration.
- **Hybrid barely moves the ceiling.** RRF improves @20 from 34.5% to 36.9%
  (two rows) while reducing @1 from 4.8% to 3.6% and @5 from 28.6% to 21.4%.
  That is not a better candidate generator at the cutoffs a proof search can
  afford.
- **The aggregate is clustered.** The 84 applicable rows come from only 14
  source files. Lexical has 29 hits at 20, 18 of them in
  `Mathlib/Algebra/BigOperators/ModEq.lean`; hybrid has 31 hits, 19 in that
  same module. The 100% lexical `simpa` result is near-duplicate
  `listSum`/`listProd` declarations, not general retrieval ability, and hybrid
  is only slightly different.
- **The families that need help are the ones retrieval misses.** `apply`,
  `exact`, `refine`, and `obtain` are at 0% at every cutoff for lexical, dense,
  and hybrid. `rw` reaches 26.1% for lexical and hybrid, but dense alone is 0%.
- **Same-module exclusion stays low.** Lexical drops to 9.5% at 20, hybrid to
  13.1%, and dense to 6.0%. Because the corpus is built from the whole library,
  near-duplicate declarations in the target's own module inflate the headline.
  A realistic future-proof evaluation needs a stronger temporal or duplicate
  control than "same module".
- **Statement text and query choice help only partially.** Name + type roughly
  triples name-only lexical recall at 20 (34.5% vs 10.7%), so the type carries
  signal. Dense and hybrid do better at rank 1 with the full goal or context +
  goal (up to 16.7%) than with the goal target, but their @20 is still at or
  below lexical. Extra context does not rescue recall.
- **Coverage is the other ceiling.** Only 24.6% of held-out rows have an
  in-corpus theorem reference at all, so even perfect retrieval could affect at
  most a quarter of these rows.

## Decision

Do not integrate lexical, dense, or hybrid retrieval into prompts, decoding, or
training. The hybrid's two-row top-20 gain over BM25 is not material, its early
precision is worse, and the hit set remains concentrated in one source module.
A model reranker over BM25 candidates could improve precision at small *k*, but
it cannot exceed the current top-20 ceiling of 36.9% on these rows, so it is
only worth running if candidate acceptance is measured by Lean rather than by
name match. A two-stage "model predicts the skeleton, retrieval fills the
lemma" design remains a candidate, but only after retrieval recall is
materially better and the leakage controls are stronger.

The more useful next measurement is probably not another retriever: with 24.6%
coverage and 0% on the `apply`/`exact`/`refine`/`obtain` families that need
lemma arguments, retrieval is not the only bottleneck. Any future attempt
should keep the same local/out-of-corpus accounting and report
kernel-verified tactic acceptance next to recall.

## Reproduction

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
python scripts/check_retrieval.py \
  --compare-report experiments/retrieval-feasibility/report.json
pytest tests/test_retrieval.py tests/test_lemma_statements.py \
  tests/test_evaluate_retrieval.py tests/test_embeddings.py \
  tests/test_build_lemma_embeddings.py tests/test_check_retrieval.py
```

The embedding build is resumable and takes roughly 40–50 minutes on CPU for
the full corpus; the evaluator then takes about two minutes. Install the
optional retrieval dependencies with `pip install -e '.[retrieval]'` (NumPy,
torch, and transformers). The dense cache is ignored by git and validated
against the corpus before use.

`scripts/build_lemma_statements.py` runs
`lake env lean --run NeuralProof/DumpStatements.lean --import Mathlib --kinds theorem`
and `lake env lean --run NeuralProof/DumpModules.lean --import Mathlib` from
`lean/` unless `--from-file` / `--modules-file` are supplied. The lexical
evaluation takes about a minute on this machine; adding the dense cache takes
about two more minutes. Both write `report.json` and `report.md`.
`report.json` holds the per-row candidate lists and all ablation tables; this
README holds the interpretation.
