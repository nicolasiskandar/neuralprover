#!/usr/bin/env python3
"""Measure lemma retrieval on held-out source targets.

The primary extraction is the shared :func:`neuralproof.lemmas.extract_symbol_heads`
used by the pre-filter.  References that appear in the proof state are reported
as *local* and are not retrieval failures.  References that are not in the
statement corpus (definitions, constructors, syntax) are reported separately.
Only target references that are theorems in the corpus count as retrieval
opportunities.

Lexical BM25 is always evaluated.  Passing ``--embeddings`` adds a dense index
over a cached embedding matrix and a reciprocal-rank-fusion hybrid.  Retrieval
recall is a diagnostic.  A retrieved name is not a verified lemma application,
and these numbers are not proof-solving performance.

    python scripts/evaluate_retrieval.py \
        --corpus data/lemma_statements.jsonl.gz \
        --output-dir experiments/retrieval-feasibility

    python scripts/evaluate_retrieval.py \
        --corpus data/lemma_statements.jsonl.gz \
        --embeddings data/cache/lemma-embeddings/all-MiniLM-L6-v2.npy \
        --output-dir experiments/retrieval-feasibility
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from neuralproof.data.provenance import sha256_file  # noqa: E402
from neuralproof.lemmas import (  # noqa: E402
    extract_symbol_heads,
    load_lemma_index,
    symbols_in_state,
)
from neuralproof.retrieval import BM25Index, iter_statements  # noqa: E402

DEFAULT_EXAMPLES = REPO_ROOT / "data" / "mathlib-info-tree-200" / "examples.jsonl"
DEFAULT_EVAL = (REPO_ROOT / "experiments" / "mathlib-info-tree-lora-200-1epoch-canonical"
                / "tactic-eval-full-heldout.json")
DEFAULT_CORPUS = REPO_ROOT / "data" / "lemma_statements.jsonl.gz"
DEFAULT_OUTPUT = REPO_ROOT / "experiments" / "retrieval-feasibility"

_IDENTIFIER = re.compile(r"[^\W\d][\w']*(?:\.[^\W\d][\w']*)*")
_TACTIC_HEADS = frozenset("""
simp simp_all simp_rw rw rewrite erw simpa dsimp apply exact refine refine' eapply
have obtain intro intros ext ext1 rcases induction cases rfl let letI change
assumption infer_instance lift by_cases by_contra use subst congr conv conv_lhs
conv_rhs replace abel grind congrm funext unfold set specialize generalize clear
rename revert constructor left right exists decide native_decide norm_num
linarith nlinarith omega positivity ring ring_nf field_simp push_cast
""".split())


def read_examples(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with path.open() as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("example_id"):
                rows[row["example_id"]] = row
    return rows


def eval_rows(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    branch = data.get("lora") or data.get("base")
    if not branch or "examples" not in branch:
        raise SystemExit(f"{path} has no lora/base examples section")
    return branch["examples"]


def is_global_reference(name: str, index, allowed: frozenset[str]) -> bool:
    parts = name.split(".")
    if name in allowed or parts[0] in allowed:
        return False
    if name in index:
        return True
    return any(".".join(parts[start:]) in index for start in range(1, len(parts)))


class NameMatcher:
    """Whether a source reference can be satisfied by a corpus declaration."""

    def __init__(self, names: list[str]):
        self.names = set(names)
        self.basenames = {name.rsplit(".", 1)[-1] for name in names}

    def contains(self, reference: str) -> bool:
        if reference in self.names:
            return True
        if reference in self.basenames:
            return True
        parts = reference.split(".")
        if any(".".join(parts[start:]) in self.names
               for start in range(1, len(parts))):
            return True
        # A reference may also be less qualified than the corpus name (for
        # example ``Foo.bar`` for ``Mathlib.Foo.bar``).  Checking the corpus
        # side keeps coverage consistent with :meth:`matches`.
        suffix = "." + reference
        return any(name.endswith(suffix) for name in self.names)

    @staticmethod
    def matches(candidate: str, reference: str, *, strict: bool) -> bool:
        if candidate == reference:
            return True
        if candidate.endswith("." + reference) or reference.endswith("." + candidate):
            return True
        if not strict:
            return (candidate.rsplit(".", 1)[-1]
                    == reference.rsplit(".", 1)[-1])
        return False


def _normalize_query(text: str) -> str:
    """Drop inaccessible-name markers and case labels from a goal rendering."""
    text = re.sub(r"✝[⁰¹²³⁴⁵⁶⁷⁸⁹]*", "", text or "")
    lines = [line for line in text.splitlines()
             if not line.strip().startswith("case ")]
    return "\n".join(lines).strip()


def _goal_target(goal_state: str) -> str:
    """The expression after the turnstile, which is the proposition to prove."""
    text = _normalize_query(goal_state)
    if "⊢" in text:
        text = text.split("⊢", 1)[1]
    return text.strip()


def target_family(target: str, syntax_kind: str) -> str:
    head = target.strip().split(maxsplit=1)[0] if target.strip() else "<empty>"
    if head in _TACTIC_HEADS:
        return head
    if head and _IDENTIFIER.fullmatch(head):
        # A bare lemma argument: report the enclosing tactic from the trace.
        kind = syntax_kind.rsplit(".", 1)[-1] if syntax_kind else ""
        return {
            "rewriteSeq": "rw",
            "allGoals": "all_goals",
            "tacticRfl": "rfl",
            "tacticInfer_instance": "infer_instance",
            "applyRfl": "apply_rfl",
        }.get(kind, kind.lower() or head)
    return head


def extract_row(examples: dict[str, dict], item: dict, index) -> dict:
    row = examples.get(item["example_id"])
    if row is None:
        raise SystemExit(f"missing corpus row {item['example_id']}")
    context = row.get("context", "")
    goal_state = row.get("goal_state", "")
    allowed = symbols_in_state(context, goal_state, row.get("theorem", ""))
    references = extract_symbol_heads(item.get("target", ""))
    local = [name for name in references
             if not is_global_reference(name, index, allowed)]
    global_refs = [name for name in references
                   if is_global_reference(name, index, allowed)]
    family = target_family(item.get("target", ""), row.get("syntax_kind", ""))
    return {
        "row": row,
        "allowed": allowed,
        "references": references,
        "local": local,
        "global": global_refs,
        "family": family,
        "query": _normalize_query(goal_state),
        "goal_target": _goal_target(goal_state),
        "context_query": _normalize_query(context + "\n" + goal_state),
        "target_module": row.get("source_file", "").removesuffix(".lean")
                                                   .replace("/", "."),
    }


def build_index(corpus: Path, include_type: bool) -> tuple[BM25Index, dict[str, set[str]]]:
    index = BM25Index()
    module_names: dict[str, set[str]] = defaultdict(set)
    for statement in iter_statements(corpus):
        index.add(statement.name, statement.document(include_type=include_type))
        if statement.module:
            module_names[statement.module].add(statement.name)
    return index.finalize(), module_names


def evaluate(rows: list[dict], index: BM25Index, matcher: NameMatcher,
             module_names: dict[str, set[str]], *, exclude_module: bool,
             query_key: str = "query", k: int = 20) -> dict[str, Any]:
    per_row = []
    for row in rows:
        excluded = {row["row"].get("source_declaration", "")}
        if exclude_module:
            excluded.update(module_names.get(row["target_module"], set()))
        results = index.search(row[query_key], k=k, exclude=excluded)
        candidates = [name for name, _ in results]
        row_hits = {}
        reference_hits = {}
        for cutoff in (1, 5, 10, 20):
            top = candidates[:cutoff]
            row_hits[cutoff] = any(
                NameMatcher.matches(candidate, reference, strict=False)
                for candidate in top for reference in row["gold"])
            reference_hits[cutoff] = sum(
                1 for reference in row["gold"]
                if any(NameMatcher.matches(candidate, reference, strict=False)
                       for candidate in top))
        strict_hits = {
            cutoff: any(
                NameMatcher.matches(candidate, reference, strict=True)
                for candidate in candidates[:cutoff] for reference in row["gold"])
            for cutoff in (1, 5, 10, 20)
        }
        per_row.append({
            "example_id": row["row"]["example_id"],
            "family": row["family"],
            "target": row["row"].get("target_tactic", ""),
            "gold": row["gold"],
            "local": row["local"],
            "top10": candidates[:10],
            "row_hit": row_hits,
            "reference_hits": reference_hits,
            "strict_row_hit": strict_hits,
        })
    return per_row


def summarize(per_row: list[dict]) -> dict[str, Any]:
    count = len(per_row)
    gold_refs = sum(len(row["gold"]) for row in per_row)
    summary: dict[str, Any] = {
        "applicable_rows": count,
        "gold_references": gold_refs,
        "recall_rows": {
            str(k): sum(row["row_hit"][k] for row in per_row) / count
            for k in (1, 5, 10, 20)
        } if count else {str(k): 0.0 for k in (1, 5, 10, 20)},
        "recall_references": {
            str(k): (sum(row["reference_hits"][k] for row in per_row) / gold_refs)
            for k in (1, 5, 10, 20)
        } if gold_refs else {str(k): 0.0 for k in (1, 5, 10, 20)},
        "strict_recall_rows": {
            str(k): sum(row["strict_row_hit"][k] for row in per_row) / count
            for k in (1, 5, 10, 20)
        } if count else {str(k): 0.0 for k in (1, 5, 10, 20)},
        "by_family": {},
    }
    families: dict[str, list[dict]] = defaultdict(list)
    for row in per_row:
        families[row["family"]].append(row)
    for family, family_rows in sorted(families.items()):
        family_refs = sum(len(row["gold"]) for row in family_rows)
        summary["by_family"][family] = {
            "rows": len(family_rows),
            "gold_references": family_refs,
            "recall_rows": {
                str(k): sum(row["row_hit"][k] for row in family_rows) / len(family_rows)
                for k in (1, 5, 10, 20)
            },
            "recall_references": {
                str(k): (sum(row["reference_hits"][k] for row in family_rows)
                         / family_refs) if family_refs else 0.0
                for k in (1, 5, 10, 20)
            },
        }
    return summary


def evaluate_dense_and_hybrid(results: dict[str, Any], args, applicable: list[dict],
                              matcher: "NameMatcher",
                              module_names: dict[str, set[str]],
                              bm25_name_type: "BM25Index",
                              corpus_names: list[str]) -> None:
    """Add dense-only and hybrid sections to ``results`` in place."""
    try:
        import numpy as np
        from neuralproof.embeddings import DenseIndex, EmbeddingEncoder, RRFRetriever
    except ImportError as error:  # pragma: no cover - dependency error path
        raise SystemExit(f"dense retrieval needs numpy: {error}") from error

    meta_path = args.embedding_meta or args.embeddings.with_suffix(".meta.json")
    if not meta_path.is_file():
        raise SystemExit(
            f"missing embedding metadata {meta_path}; run scripts/build_lemma_embeddings.py")
    meta = json.loads(meta_path.read_text())
    corpus_sha = sha256_file(args.corpus)
    if meta.get("corpus_sha256") != corpus_sha:
        raise SystemExit("the embedding cache was built from a different corpus")
    if meta.get("rows") != len(corpus_names):
        raise SystemExit("the embedding cache row count does not match the corpus")
    if meta.get("output_sha256") != sha256_file(args.embeddings):
        raise SystemExit("the embedding matrix does not match its recorded digest")

    model = args.dense_model or meta["model"]
    revision = args.dense_revision or meta["revision"]
    pooling = args.dense_pooling or meta["pooling"]
    max_length = args.dense_max_length or meta["max_length"]
    for label, given in (("model", model), ("revision", revision),
                         ("pooling", pooling), ("max_length", max_length)):
        recorded = meta[label]
        if given != recorded:
            raise SystemExit(
                f"--dense-{'max-length' if label == 'max_length' else label} "
                f"{given!r} does not match the cache ({recorded!r})")

    encoder = EmbeddingEncoder(
        model, revision, pooling=pooling, max_length=max_length,
        batch_size=args.dense_batch_size, threads=args.dense_threads)
    embeddings = np.load(args.embeddings, mmap_mode="r")
    if embeddings.shape[0] != len(corpus_names):
        raise SystemExit("the embedding matrix and corpus have different row counts")
    if embeddings.shape[1] != encoder.dimension:
        raise SystemExit(
            f"embedding dimension {embeddings.shape[1]} does not match "
            f"the encoder ({encoder.dimension})")
    dense = DenseIndex(corpus_names, embeddings, encoder=encoder,
                       normalize=not meta.get("normalized", False))

    dense_primary = evaluate(applicable, dense, matcher, module_names,
                             exclude_module=False, query_key="goal_target")
    dense_full = evaluate(applicable, dense, matcher, module_names,
                          exclude_module=False, query_key="query")
    dense_context = evaluate(applicable, dense, matcher, module_names,
                             exclude_module=False, query_key="context_query")
    dense_excluded = evaluate(applicable, dense, matcher, module_names,
                              exclude_module=True, query_key="goal_target")
    results["dense"] = {
        "corpus_documents": dense.size,
        "primary": summarize(dense_primary),
        "full_goal": summarize(dense_full),
        "context_goal": summarize(dense_context),
        "same_module_excluded": summarize(dense_excluded),
        "rows": dense_primary,
    }

    hybrid = RRFRetriever([bm25_name_type, dense], depth=args.hybrid_depth,
                          k=args.rrf_k)
    hybrid_primary = evaluate(applicable, hybrid, matcher, module_names,
                              exclude_module=False, query_key="goal_target")
    hybrid_full = evaluate(applicable, hybrid, matcher, module_names,
                           exclude_module=False, query_key="query")
    hybrid_context = evaluate(applicable, hybrid, matcher, module_names,
                              exclude_module=False, query_key="context_query")
    hybrid_excluded = evaluate(applicable, hybrid, matcher, module_names,
                               exclude_module=True, query_key="goal_target")
    results["hybrid"] = {
        "primary": summarize(hybrid_primary),
        "full_goal": summarize(hybrid_full),
        "context_goal": summarize(hybrid_context),
        "same_module_excluded": summarize(hybrid_excluded),
        "rows": hybrid_primary,
    }

    results["protocol"]["dense"] = {
        "model": model,
        "revision": revision,
        "pooling": pooling,
        "max_length": max_length,
        "normalized": bool(meta.get("normalized", False)),
        "rows": int(embeddings.shape[0]),
        "dim": int(embeddings.shape[1]),
        "embedding_sha256": meta.get("output_sha256"),
        "corpus_sha256": corpus_sha,
        "tuning": "none; the model, revision and pooling were fixed before evaluation",
    }
    results["protocol"]["hybrid"] = {
        "fusion": "reciprocal rank fusion",
        "retrievers": ["bm25 name+type", "dense"],
        "weights": [1.0, 1.0],
        "depth": args.hybrid_depth,
        "rrf_k": args.rrf_k,
        "tuning": "none; depth and k were fixed before evaluation",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=Path, default=DEFAULT_EXAMPLES)
    parser.add_argument("--eval", type=Path, default=DEFAULT_EVAL)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--index", type=Path,
                        default=REPO_ROOT / "data" / "lemma_index.json.gz")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0,
                        help="evaluate only the first N eval rows (0 = all)")
    parser.add_argument("--embeddings", type=Path,
                        help="cached .npy embedding matrix row-aligned with the corpus")
    parser.add_argument("--embedding-meta", type=Path,
                        help="metadata for --embeddings; defaults to <embeddings>.meta.json")
    parser.add_argument("--dense-model", help="encoder model; defaults to the cache metadata")
    parser.add_argument("--dense-revision", help="encoder revision; defaults to the cache metadata")
    parser.add_argument("--dense-pooling", choices=("mean", "cls"),
                        help="pooling; defaults to the cache metadata")
    parser.add_argument("--dense-max-length", type=int,
                        help="token truncation; defaults to the cache metadata")
    parser.add_argument("--dense-batch-size", type=int, default=128,
                        help="query batch size for the encoder")
    parser.add_argument("--dense-threads", type=int, default=0,
                        help="torch CPU threads; 0 keeps the torch default")
    parser.add_argument("--hybrid-depth", type=int, default=50,
                        help="candidates from each retriever before RRF fusion")
    parser.add_argument("--rrf-k", type=float, default=60.0,
                        help="RRF damping constant (fixed before evaluation)")
    args = parser.parse_args(argv)

    examples = read_examples(args.examples)
    items = eval_rows(args.eval)
    if args.limit:
        items = items[:args.limit]
    index = load_lemma_index(args.index, required=True)
    extracted = [extract_row(examples, item, index) for item in items]

    corpus_names = [statement.name for statement in iter_statements(args.corpus)]
    matcher = NameMatcher(corpus_names)
    categories: Counter[str] = Counter()
    for row in extracted:
        in_corpus = [name for name in row["global"] if matcher.contains(name)]
        out_of_corpus = [name for name in row["global"] if not matcher.contains(name)]
        row["gold"] = in_corpus
        row["out_of_corpus"] = out_of_corpus
        if in_corpus:
            categories["in_corpus"] += 1
        elif out_of_corpus:
            categories["out_of_corpus_only"] += 1
        elif row["local"]:
            categories["local_only"] += 1
        elif row["references"]:
            categories["unknown_only"] += 1
        else:
            categories["no_reference"] += 1
    applicable = [row for row in extracted if row["gold"]]

    results: dict[str, Any] = {
        "protocol": {
            "total_eval_rows": len(items),
            "applicable_rows": len(applicable),
            "coverage": len(applicable) / len(items) if items else 0.0,
            "extraction": "neuralproof.lemmas.extract_symbol_heads",
            "query": "goal target after ⊢ (primary); full goal state and context + goal (ablations)",
            "exclusion": "target declaration only",
            "gold": "target references that are theorems in the statement corpus",
            "matching": "relaxed name match (qualified suffix or basename)",
            "caveat": "recall is a diagnostic; Lean is the authority for proof acceptance",
        },
        "applicability": dict(sorted(categories.items())),
        "global_references": sum(len(row["global"]) for row in extracted),
        "local_references": sum(len(row["local"]) for row in extracted),
        "out_of_corpus_references": Counter(
            name for row in extracted for name in row["out_of_corpus"]),
    }
    results["out_of_corpus_references"] = dict(
        results["out_of_corpus_references"].most_common())

    bm25_name_type = None
    module_names: dict[str, set[str]] = {}
    for label, include_type in (("name_only", False), ("name_and_type", True)):
        bm25, module_names = build_index(args.corpus, include_type)
        if include_type:
            bm25_name_type = bm25
        goal_rows = evaluate(applicable, bm25, matcher, module_names,
                             exclude_module=False, query_key="goal_target")
        full_goal_rows = evaluate(applicable, bm25, matcher, module_names,
                                  exclude_module=False, query_key="query")
        context_rows = evaluate(applicable, bm25, matcher, module_names,
                                exclude_module=False, query_key="context_query")
        strict_rows = evaluate(applicable, bm25, matcher, module_names,
                               exclude_module=True, query_key="goal_target")
        results[label] = {
            "corpus_documents": bm25.size,
            "primary": summarize(goal_rows),
            "full_goal": summarize(full_goal_rows),
            "context_goal": summarize(context_rows),
            "same_module_excluded": summarize(strict_rows),
            "rows": goal_rows,
        }

    if args.embeddings is not None:
        evaluate_dense_and_hybrid(results, args, applicable, matcher,
                                  module_names, bm25_name_type, corpus_names)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n")

    # Markdown is a readable view of the same machine-readable report.
    lines = [
        "# Retrieval Feasibility",
        "",
        "Lexical BM25 retrieval over Mathlib theorem statements, plus dense and",
        "hybrid sections when a cached embedding matrix is supplied. Recall is a",
        "diagnostic; a retrieved name is not a verified lemma application.",
        "",
        "## Coverage",
        "",
        f"- Eval rows: {results['protocol']['total_eval_rows']}",
        f"- Applicable rows (at least one in-corpus global target lemma): "
        f"{results['protocol']['applicable_rows']} "
        f"({results['protocol']['coverage']:.1%})",
        f"- Applicability: {results['applicability']}",
        f"- Global target references: {results['global_references']}; "
        f"local references: {results['local_references']} "
        "(local references are not retrieval failures)",
        f"- Out-of-corpus global references (not retrieval failures): "
        f"{results['out_of_corpus_references']}",
        "",
        "## Recall by query (relaxed name match)",
        "",
        "| index | query | @1 | @5 | @10 | @20 |",
        "| :-- | :-- | --: | --: | --: | --: |",
    ]
    for label, title in (("name_only", "name only"),
                         ("name_and_type", "name + type")):
        for section, query_title in (("primary", "goal target"),
                                     ("full_goal", "full goal state"),
                                     ("context_goal", "context + goal")):
            table = results[label][section]["recall_rows"]
            lines.append(f"| {title} | {query_title} | {table['1']:.1%} | "
                         f"{table['5']:.1%} | {table['10']:.1%} | "
                         f"{table['20']:.1%} |")
    lines += ["", "## Strict name matching (row-level)", "",
              "| index | query | @1 | @5 | @10 | @20 |",
              "| :-- | :-- | --: | --: | --: | --: |"]
    for label, title in (("name_only", "name only"),
                         ("name_and_type", "name + type")):
        for section, query_title in (("primary", "goal target"),
                                     ("full_goal", "full goal state"),
                                     ("context_goal", "context + goal")):
            table = results[label][section]["strict_recall_rows"]
            lines.append(f"| {title} | {query_title} | {table['1']:.1%} | "
                         f"{table['5']:.1%} | {table['10']:.1%} | "
                         f"{table['20']:.1%} |")
    lines += ["", "## Same-module exclusion (leakage control, goal target)", "",
              "Removes every declaration defined in the target's source module.",
              "",
              "| index | @1 | @5 | @10 | @20 |",
              "| :-- | --: | --: | --: | --: |"]
    for label, title in (("name_only", "name only"),
                         ("name_and_type", "name + type")):
        table = results[label]["same_module_excluded"]["recall_rows"]
        lines.append(f"| {title} | {table['1']:.1%} | {table['5']:.1%} | "
                     f"{table['10']:.1%} | {table['20']:.1%} |")
    lines += ["", "## By tactic family (name + type, goal target)", "",
              "| family | rows | @1 | @5 | @10 | @20 |",
              "| :-- | --: | --: | --: | --: | --: |"]
    for family, row in results["name_and_type"]["primary"]["by_family"].items():
        table = row["recall_rows"]
        lines.append(f"| `{family}` | {row['rows']} | {table['1']:.1%} | "
                     f"{table['5']:.1%} | {table['10']:.1%} | {table['20']:.1%} |")
    lines += ["", "## Reference-level recall (goal target)", "",
              "| index | @1 | @5 | @10 | @20 |",
              "| :-- | --: | --: | --: | --: |"]
    for label, title in (("name_only", "name only"),
                         ("name_and_type", "name + type")):
        table = results[label]["primary"]["recall_references"]
        lines.append(f"| {title} | {table['1']:.1%} | {table['5']:.1%} | "
                     f"{table['10']:.1%} | {table['20']:.1%} |")
    if args.embeddings is not None:
        dense_info = results["protocol"]["dense"]
        hybrid_info = results["protocol"]["hybrid"]
        lines += [
            "",
            "## Dense and hybrid retrieval",
            "",
            f"- Encoder: `{dense_info['model']}` at revision "
            f"`{dense_info['revision']}` ({dense_info['pooling']} pooling, "
            f"max length {dense_info['max_length']}, "
            f"embedding SHA-256 `{dense_info['embedding_sha256']}`).",
            f"- Hybrid: reciprocal rank fusion of BM25 name + type and dense, "
            f"depth {hybrid_info['depth']}, k={hybrid_info['rrf_k']}, equal weights.",
            "- The model, revision, pooling, depth and k were fixed before",
            "  evaluation; nothing was tuned on the held-out targets.",
            "",
            "| retriever | query | @1 | @5 | @10 | @20 |",
            "| :-- | :-- | --: | --: | --: | --: |",
        ]
        for label, title in (("dense", "dense"), ("hybrid", "hybrid")):
            for section, query_title in (("primary", "goal target"),
                                         ("full_goal", "full goal state"),
                                         ("context_goal", "context + goal")):
                table = results[label][section]["recall_rows"]
                lines.append(f"| {title} | {query_title} | {table['1']:.1%} | "
                             f"{table['5']:.1%} | {table['10']:.1%} | "
                             f"{table['20']:.1%} |")
        lines += [
            "",
            "### Dense and hybrid same-module exclusion (goal target)",
            "",
            "| retriever | @1 | @5 | @10 | @20 |",
            "| :-- | --: | --: | --: | --: |",
        ]
        for label, title in (("dense", "dense"), ("hybrid", "hybrid")):
            table = results[label]["same_module_excluded"]["recall_rows"]
            lines.append(f"| {title} | {table['1']:.1%} | {table['5']:.1%} | "
                         f"{table['10']:.1%} | {table['20']:.1%} |")
        lines += [
            "",
            "### Dense and hybrid by tactic family (goal target)",
            "",
            "| retriever | family | rows | @1 | @5 | @10 | @20 |",
            "| :-- | :-- | --: | --: | --: | --: | --: |",
        ]
        for label, title in (("dense", "dense"), ("hybrid", "hybrid")):
            for family, row in results[label]["primary"]["by_family"].items():
                table = row["recall_rows"]
                lines.append(f"| {title} | `{family}` | {row['rows']} | "
                             f"{table['1']:.1%} | {table['5']:.1%} | "
                             f"{table['10']:.1%} | {table['20']:.1%} |")
    lines += [
        "",
        "## Notes",
        "",
        "- The denominator is the applicable rows; local-only and no-reference",
        "  rows are not retrieval failures.",
        "- Target references that are not theorems in the corpus (definitions,",
        "  constructors, syntax) are listed in `report.json` and are not counted",
        "  as retrieval failures.",
        "- ``same_module_excluded`` is a conservative leakage control. It is too",
        "  strict because the target lemma often lives in the same source module.",
        "- A retrieval hit is not a verified lemma application; Lean is the",
        "  authority for proof acceptance.",
        "",
    ]
    (args.output_dir / "report.md").write_text("\n".join(lines) + "\n")

    summary_keys = ["name_only", "name_and_type"]
    if args.embeddings is not None:
        summary_keys += ["dense", "hybrid"]
    print(json.dumps({key: results[key]["primary"]["recall_rows"]
                      for key in summary_keys}, indent=2))
    print(f"Applicable rows: {len(applicable)}/{len(items)}")
    print(f"Report written to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
