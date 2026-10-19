# Mathlib corpus extraction

## Native InfoTree tracing

Use the Lean frontend driver to get tactic nodes and their before/after goals
from elaboration itself:

```bash
neuralproof data trace \
  --file lean/.lake/packages/mathlib/Mathlib/Algebra/AddConstMap/Basic.lean \
  --output data/traces/addconstmap-basic.json
```

This uses the pinned Lean `InfoTree` API and outputs raw tactic nodes with
declaration name, syntax, goal state, resulting state, and completion flag.
Nested tactic combinators can produce overlapping nodes; consumers should
filter by syntax kind/range and preserve them in raw trace data rather than
assuming each node is one top-level tactic step. The driver runs the real Lean
frontend over the source file and reports its elaboration diagnostics.

## Corpus extraction and scope

`scripts/extract_mathlib_corpus.py` selects a deterministic prefix of sorted
`Mathlib/**/*.lean` paths from the pinned Mathlib revision. It resumes at file
boundaries using `completed.json`, writes examples incrementally to
`examples.jsonl`, and retains per-file diagnostics in `file_stats.jsonl`.
The manifest records the exact selected-file hash and the split seed.

The JSONL corpus command is a conservative source recognizer plus Lean replay.
It recognizes simple single-line declaration headers and one-line tactic
bodies, then accepts a row only when the tactic replay closes the goal and the
proof passes Lean verification. Its context contains the source file's imports
and currently active namespace/open/variable/local directives; it deliberately
does not import `Mathlib` wholesale, which could include the theorem being
mined. Earlier declarations in the same source file are not copied into this
context, so replay failures caused by missing local declarations remain
visible in stats. Multi-tactic proofs, nested syntax, and elaborator macro
expansions remain unsupported by this supervised-row exporter.

`neuralproof data trace` is the native InfoTree path. The driver captures
enclosing command spans as well as tactic Info nodes, preserving the original
declaration and prior source context for replay. Normalize one trace with:

```bash
neuralproof data normalize-trace \
  --trace data/traces/nat-basic.json \
  --source lean/.lake/packages/mathlib/Mathlib/Data/Nat/Basic.lean \
  --output data/normalized/nat-basic.jsonl
```

The normalizer keeps source-backed `Lean.Parser.Tactic` spans, resolves missing
declaration names only through a unique enclosing `byTactic` span, deduplicates
nodes sharing a source span, and uses source text rather than pretty-printed
InfoTree syntax as the label. It emits `result_state`, source byte offsets,
syntax kind, source revision, file-level split, and a validation marker. The
original complete file must elaborate for the trace to exist, so each selected
transition was observed during successful source elaboration. To check replay
in its actual prefix context, run:

```bash
neuralproof data replay-trace \
  --source lean/.lake/packages/mathlib/Mathlib/Data/Nat/Basic.lean \
  --output data/validated/nat-basic.jsonl \
  --stats data/validated/nat-basic.stats.json
```

This replays the latest normalized tactic prefix per declaration, which checks
all earlier tactics on that path. Ordinary prefixes are compiled with
`all_goals sorry` after the selected tactic so remaining goals do not block
elaboration. Thus `replayed` means the prefix was accepted by Lean; it does not
mean the theorem was completed or verified. Some syntax (notably incomplete
`induction ... with` branches) cannot be cut at an arbitrary tactic boundary;
those entries fall back to compiling the original complete declaration and
are marked `declaration_replayed`. That status confirms the source declaration
elaborated, not that its proof is free of `sorry` or unexpected axioms. Failed
or timed out replays are retained with diagnostics in the stats file. The
validation annotation is shared by all normalized rows of a declaration.

On pinned `Mathlib/Data/Nat/Basic.lean`, the trace contained 1,463 tactic nodes
and 64 command nodes, normalized to 40 examples in 11 declarations. The replay
pilot checked all 11: nine tactic prefixes and two complete-declaration
fallbacks succeeded. This is a small smoke sample, not a corpus-scale result.

For a resumable file tranche, use:

```bash
neuralproof data trace-corpus --files 200 \
  --output data/mathlib-info-tree-200
neuralproof preprocess \
  --input data/mathlib-info-tree-200/examples.jsonl \
  --output data/mathlib-info-tree-200/processed
```

The command checkpoints after each source file. `summary.json` records the
selected-file hash, file-level split counts, failed source files, duplicate
IDs, broad-import audit, and declaration-name split overlap. Resume only with
the same file selection and timeout configuration; use a new output directory
for a different run. Staged-corpus examples have not been processed by
`data replay-trace`; their contexts remain pending validation. This is a
tactic-prediction dataset, not a collection of separately verified scripts.

## Record schema

Replay-verified rows contain `theorem_id`, `theorem`, `context`, `goal_state`,
`target_tactic`, `source_file`, `source_line`, `source_declaration`,
`source_revision`, and `split`. Normalized InfoTree rows instead use a
source-unique `example_id`, a path-qualified `theorem_id`, and additionally
contain `result_state`, `completed_after_tactic`, byte offsets, `syntax_kind`,
and a `validation` marker. Both schemas retain `context`, `goal_state`,
`target_tactic`, source metadata, and file-level split for supervised training.
Splits are assigned from the source file path
and seed so all extracted declarations in one file stay in one split. The
synthetic theorem ID includes both the source path and fully qualified source
declaration so names reused in different namespaces do not collide. This
reduces theorem leakage but does not prevent related lemmas in different files
from crossing splits.

## Run and resume

```bash
python scripts/extract_mathlib_corpus.py --files 200 --per-file 5 \
  --output data/mathlib-200
```

Rerun the same command to continue. Use a new output path to start a distinct
corpus; `--no-resume` resets the JSONL outputs. `summary.json` records counts by
split and total reported extraction failures. These values describe actual
completed files only; they should not be presented as full Mathlib coverage.
