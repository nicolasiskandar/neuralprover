# Lemma-filter plumbing diagnostic

This is a plumbing check, not a benchmark and not a model sample. It uses the
25-row replay corpus with an artificial fixed candidate list
`rw [not_a_lemma_anywhere], rfl` at one node and width two, once without the
lemma pre-filter and once with `--filter-invalid-lemmas`.

```bash
python -m neuralproof.cli evaluate \
  --data data/mathlib-200/examples.jsonl \
  --output experiments/lemma-filter-plumbing/off/results.jsonl \
  --nodes 1 --width 2 --tactics "rw [not_a_lemma_anywhere],rfl"

python -m neuralproof.cli evaluate \
  --data data/mathlib-200/examples.jsonl \
  --output experiments/lemma-filter-plumbing/on/results.jsonl \
  --nodes 1 --width 2 --tactics "rw [not_a_lemma_anywhere],rfl" \
  --filter-invalid-lemmas
```

| run | tactic calls/problem | invalid tactics | rejected unknown | verified |
| :-- | ---: | ---: | ---: | ---: |
| filter off | 2.0 | 50 | 0 | 0/25 |
| filter on | 1.0 | 25 | 25 | 0/25 |

The filter removes one Lean call per problem because the unknown `rw` candidate
never reaches Lean. Both runs prove nothing. The candidate list is fixed by
hand, so these numbers say nothing about the model or about proof-solving
performance; the measured false-reject result is in
`experiments/lemma-filter-report.json`.
