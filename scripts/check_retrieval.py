#!/usr/bin/env python3
"""Check the lemma-retrieval setup end to end.

This packages the retrieval workflow that was previously run as ad-hoc
commands: corpus/embedding integrity, index smoke tests, custom queries, and a
small held-out sanity run.  It is a diagnostic tool, not a benchmark: recall is
printed, never asserted, and a retrieved name is not a verified lemma
application.  Lean remains the authority for proof acceptance.

Exit status is non-zero only for structural failures (missing or inconsistent
cache, failed self-retrieval probe, missing required input).  Low recall does
not fail the check.  Use ``--require-dense`` / ``--require-heldout`` to turn an
explicit skip into a failure in CI.

    python scripts/check_retrieval.py
    python scripts/check_retrieval.py --no-dense
    python scripts/check_retrieval.py --sample 50 \
        --json /tmp/opencode/retrieval/check.json
    python scripts/check_retrieval.py --retriever dense \
        --query "Finset.sum_comm"
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from neuralproof.data.provenance import sha256_file  # noqa: E402
from neuralproof.retrieval import BM25Index, iter_statements  # noqa: E402

DEFAULT_CORPUS = REPO_ROOT / "data" / "lemma_statements.jsonl.gz"
DEFAULT_EMBEDDINGS = (REPO_ROOT / "data" / "cache" / "lemma-embeddings"
                      / "all-MiniLM-L6-v2.npy")
DEFAULT_EXAMPLES = REPO_ROOT / "data" / "mathlib-info-tree-200" / "examples.jsonl"
DEFAULT_EVAL = (REPO_ROOT / "experiments" / "mathlib-info-tree-lora-200-1epoch-canonical"
                / "tactic-eval-full-heldout.json")
DEFAULT_INDEX = REPO_ROOT / "data" / "lemma_index.json.gz"
DEFAULT_REPORT = REPO_ROOT / "experiments" / "retrieval-feasibility" / "report.json"

RETRIEVERS = ("lexical", "dense", "hybrid")


class Report:
    """Collect checks and the human-readable transcript in one place."""

    def __init__(self) -> None:
        self.checks: list[dict[str, str]] = []
        self.lines: list[str] = []
        self.data: dict[str, Any] = {}
        self.protocol: dict[str, Any] = {}
        self.failures = 0
        self.warnings = 0

    def _add(self, name: str, status: str, detail: str) -> None:
        self.checks.append({"name": name, "status": status, "detail": detail})
        self.lines.append(f"[{status.upper()}] {name}: {detail}")
        if status == "fail":
            self.failures += 1
        elif status == "warn":
            self.warnings += 1

    def pass_(self, name: str, detail: str) -> None:
        self._add(name, "pass", detail)

    def skip(self, name: str, detail: str) -> None:
        self._add(name, "skip", detail)

    def fail(self, name: str, detail: str) -> None:
        self._add(name, "fail", detail)

    def warn(self, name: str, detail: str) -> None:
        self._add(name, "warn", detail)

    def heading(self, text: str) -> None:
        self.lines.extend(["", f"== {text} =="])

    def line(self, text: str = "") -> None:
        self.lines.append(text)


def load_evaluator():
    """Load the evaluation script so extraction cannot drift from the report."""
    path = REPO_ROOT / "scripts" / "evaluate_retrieval.py"
    spec = importlib.util.spec_from_file_location("check_retrieval_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def derived_corpus_meta(corpus: Path) -> Path:
    """``foo.jsonl.gz`` -> ``foo.meta.json`` beside the corpus."""
    without_gzip = corpus.with_suffix("") if corpus.suffix == ".gz" else corpus
    return without_gzip.with_suffix(".meta.json")


def evenly_spaced(rows: Sequence[dict], count: int) -> list[dict]:
    """Deterministically spread ``count`` rows over the applicable set."""
    if count <= 0 or count >= len(rows):
        return list(rows)
    if count == 1:
        return [rows[len(rows) // 2]]
    indices = [round(index * (len(rows) - 1) / (count - 1))
               for index in range(count)]
    return [rows[index] for index in indices]


def build_lexical(corpus: Path, report: Report):
    """Build BM25 name+type while collecting probes and module membership."""
    total = sum(1 for _ in iter_statements(corpus))
    if total == 0:
        report.fail("corpus", f"{corpus} contains no statement rows")
        return None
    probe_indices = {total // 4, total // 2, (3 * total) // 4}
    index = BM25Index()
    names: list[str] = []
    module_names: dict[str, set[str]] = defaultdict(set)
    probes: dict[int, Any] = {}
    for position, statement in enumerate(iter_statements(corpus)):
        names.append(statement.name)
        index.add(statement.name, statement.document(include_type=True))
        if statement.module:
            module_names[statement.module].add(statement.name)
        if position in probe_indices:
            probes[position] = statement
    index.finalize()

    report.pass_("corpus", f"{total} statement rows from {corpus}")
    if index.size != total:
        report.fail("bm25 index", f"{index.size} documents, expected {total}")
    else:
        report.pass_("bm25 index", f"name + type over {index.size} documents")
    return total, names, index, dict(module_names), probes


def check_corpus_meta(corpus: Path, total: int, corpus_sha: str | None,
                      meta_path: Path, report: Report) -> None:
    if not meta_path.is_file():
        report.skip("corpus provenance",
                    f"no {meta_path}; pass --corpus-meta to check one")
        return
    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError as error:
        report.fail("corpus provenance", f"{meta_path} is not valid JSON: {error}")
        return
    if corpus_sha is None:
        report.skip("corpus digest", "not checked (--skip-digests)")
    elif meta.get("output_sha256") != corpus_sha:
        report.fail("corpus digest",
                    f"{corpus} does not match the recorded digest in {meta_path}")
    else:
        report.pass_("corpus digest", f"SHA-256 {corpus_sha}")
    recorded_rows = meta.get("output_count")
    if recorded_rows is None:
        report.skip("corpus rows", f"{meta_path} records no output_count")
    elif recorded_rows != total:
        report.fail("corpus rows",
                    f"{meta_path} records {recorded_rows}, corpus has {total}")
    else:
        report.pass_("corpus rows", f"{total} rows")


def setup_dense(args: argparse.Namespace, corpus: Path, corpus_rows: int,
                corpus_sha: str | None, names: Sequence[str],
                report: Report) -> dict[str, Any] | None:
    """Validate the embedding cache and build a dense index, or explain why not."""

    def unavailable(reason: str) -> None:
        (report.fail if args.require_dense else report.skip)("dense", reason)
        return None

    if args.no_dense:
        report.skip("dense", "disabled by --no-dense")
        return None
    selected = args.retriever or list(RETRIEVERS)
    if not any(label in selected for label in ("dense", "hybrid")):
        report.skip("dense", "not selected by --retriever")
        return None
    if not args.embeddings.is_file():
        return unavailable(
            f"missing embedding cache {args.embeddings}; run "
            "scripts/build_lemma_embeddings.py or pass --no-dense")
    meta_path = args.embedding_meta or args.embeddings.with_suffix(".meta.json")
    if not meta_path.is_file():
        return unavailable(
            f"missing embedding metadata {meta_path}; run "
            "scripts/build_lemma_embeddings.py")
    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError as error:
        report.fail("dense metadata", f"{meta_path} is not valid JSON: {error}")
        return None

    valid = True
    if args.skip_digests:
        report.skip("embedding digests", "not checked (--skip-digests)")
    else:
        recorded_corpus = meta.get("corpus_sha256")
        if corpus_sha is None:
            corpus_sha = sha256_file(corpus)
        if recorded_corpus != corpus_sha:
            report.fail("embedding corpus digest",
                        "the cache was built from a different corpus")
            valid = False
        else:
            report.pass_("embedding corpus digest", f"SHA-256 {corpus_sha}")
        recorded_matrix = meta.get("output_sha256")
        actual_matrix = sha256_file(args.embeddings)
        if recorded_matrix != actual_matrix:
            report.fail("embedding matrix digest",
                        "the matrix does not match its recorded digest")
            valid = False
        else:
            report.pass_("embedding matrix digest", f"SHA-256 {actual_matrix}")

    if meta.get("rows") != corpus_rows:
        report.fail("embedding rows",
                    f"cache records {meta.get('rows')}, corpus has {corpus_rows}")
        valid = False
    else:
        report.pass_("embedding rows", f"{corpus_rows} rows")
    if not isinstance(meta.get("dim"), int) or meta["dim"] <= 0:
        report.fail("embedding dimension", f"cache records {meta.get('dim')!r}")
        valid = False
    missing_keys = [key for key in ("model", "revision", "pooling", "max_length")
                    if meta.get(key) is None]
    if missing_keys:
        report.fail("dense metadata",
                    f"{meta_path} is missing {', '.join(missing_keys)}")
        valid = False

    settings = {
        "model": args.dense_model,
        "revision": args.dense_revision,
        "pooling": args.dense_pooling,
        "max_length": args.dense_max_length,
    }
    for key, given in settings.items():
        if given is not None and given != meta.get(key):
            report.fail(f"dense {key}",
                        f"{given!r} does not match the cache ({meta.get(key)!r})")
            valid = False
    if not valid:
        return None

    try:
        import numpy as np
    except ImportError as error:  # pragma: no cover - dependency error path
        return unavailable(f"dense retrieval needs numpy: {error}")

    try:
        matrix = np.load(args.embeddings, mmap_mode="r")
    except (OSError, ValueError) as error:
        report.fail("embedding matrix", f"cannot load {args.embeddings}: {error}")
        return None
    if matrix.ndim != 2:
        report.fail("embedding matrix", f"expected a 2-D matrix, got {matrix.shape}")
        return None
    if matrix.shape[0] != corpus_rows:
        report.fail("embedding matrix",
                    f"matrix has {matrix.shape[0]} rows, corpus has {corpus_rows}")
        return None
    if matrix.shape[1] != meta.get("dim"):
        report.fail("embedding matrix",
                    f"matrix has {matrix.shape[1]} columns, cache records "
                    f"{meta.get('dim')}")
        return None
    if matrix.dtype != np.float32:
        report.fail("embedding dtype", f"expected float32, got {matrix.dtype}")
        return None

    if args.full_integrity:
        finite = True
        minimum, maximum = float("inf"), 0.0
        for start in range(0, matrix.shape[0], 65536):
            chunk = np.asarray(matrix[start:start + 65536])
            if not np.isfinite(chunk).all():
                finite = False
                break
            norms = np.linalg.norm(chunk, axis=1)
            minimum = min(minimum, float(norms.min()))
            maximum = max(maximum, float(norms.max()))
        if not finite:
            report.fail("embedding values", "the matrix contains non-finite values")
            return None
        if meta.get("normalized") and not (abs(minimum - 1.0) < 1e-4
                                           and abs(maximum - 1.0) < 1e-4):
            report.fail("embedding norm",
                        f"normalized rows should have norm 1, saw [{minimum:.6f}, "
                        f"{maximum:.6f}]")
            return None
        report.pass_("embedding values",
                     f"finite rows; norm range [{minimum:.6f}, {maximum:.6f}]")
    else:
        count = min(matrix.shape[0], 1024)
        indices = np.unique(np.linspace(0, matrix.shape[0] - 1, count)
                            .astype(np.int64))
        sample = np.asarray(matrix[indices])
        if not np.isfinite(sample).all():
            report.fail("embedding values", "sampled rows contain non-finite values")
            return None
        if meta.get("normalized"):
            norms = np.linalg.norm(sample, axis=1)
            if not np.allclose(norms, 1.0, atol=1e-4):
                report.fail("embedding norm",
                            "sampled normalized rows are not unit length; rerun "
                            "with --full-integrity to check every row")
                return None
            report.pass_("embedding values",
                         f"{len(indices)} sampled rows finite and unit-normalized")
        else:
            report.pass_("embedding values",
                         f"{len(indices)} sampled rows finite (cache is not normalized)")

    try:
        from neuralproof.embeddings import DenseIndex, EmbeddingEncoder
    except ImportError as error:  # pragma: no cover - dependency error path
        return unavailable(f"dense retrieval needs numpy: {error}")

    try:
        encoder = EmbeddingEncoder(
            meta["model"], meta.get("revision"), pooling=meta.get("pooling", "mean"),
            max_length=meta.get("max_length", 128),
            batch_size=args.dense_batch_size, threads=args.dense_threads)
    except (ImportError, RuntimeError, OSError, ValueError) as error:
        return unavailable(
            f"could not load the encoder ({error}); install with "
            "`pip install -e '.[retrieval]'` or pass --no-dense")
    if encoder.dimension != matrix.shape[1]:
        report.fail("encoder dimension",
                    f"encoder returns {encoder.dimension}, matrix has "
                    f"{matrix.shape[1]}")
        return None
    report.pass_("dense encoder",
                 f"{meta['model']} @ {meta.get('revision')} "
                 f"({meta.get('pooling')} pooling, max length "
                 f"{meta.get('max_length')}, dimension {encoder.dimension})")

    index = DenseIndex(names, matrix, encoder=encoder,
                       normalize=not meta.get("normalized", False))
    report.pass_("dense index", f"{index.size} rows from {args.embeddings}")
    return {"meta": meta, "matrix": matrix, "encoder": encoder, "index": index}


def check_self_retrieval(retrievers: dict[str, Any], probes: dict[int, Any],
                         report: Report, k: int) -> list[dict[str, Any]]:
    """A declaration's own text should retrieve that declaration."""
    records: list[dict[str, Any]] = []
    for position in sorted(probes):
        statement = probes[position]
        text = statement.document(include_type=True)
        for label, retriever in retrievers.items():
            ranked = retriever.search(text, k=k)
            names = [name for name, _ in ranked]
            rank = names.index(statement.name) + 1 if statement.name in names else None
            ok = rank is not None and rank <= 5
            name = f"{label} self-retrieval"
            detail = f"{statement.name} at rank {rank} for its own statement"
            (report.pass_ if ok else report.fail)(name, detail)
            report.line(f"  {label}: {statement.name} -> rank {rank}")
            records.append({"position": position, "retriever": label,
                            "name": statement.name, "rank": rank, "ok": ok})

            excluded = retriever.search(text, k=k, exclude=[statement.name])
            still_there = statement.name in {candidate for candidate, _ in excluded}
            (report.fail if still_there else report.pass_)(
                f"{label} exclusion",
                f"{statement.name} {'still present' if still_there else 'removed'} "
                "when excluded")
    return records


def run_custom_queries(retrievers: dict[str, Any], queries: Iterable[str],
                       report: Report, k: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for query in queries:
        report.line(f"query: {query}")
        record: dict[str, Any] = {"query": query, "results": {}}
        for label, retriever in retrievers.items():
            ranked = retriever.search(query, k=k)
            record["results"][label] = [
                {"name": name, "score": score} for name, score in ranked]
            preview = ", ".join(
                f"{name} ({score:.4g})" for name, score in ranked[:5]) or "<none>"
            report.line(f"  {label}: {preview}")
            if not ranked:
                report.warn(f"{label} query",
                            f"no candidates for {query!r}; the query may contain "
                            "only common or stopword terms")
        records.append(record)
    return records


def run_heldout(args: argparse.Namespace, report: Report,
                retrievers: dict[str, Any], names: Sequence[str],
                module_names: dict[str, set[str]]) -> dict[str, Any]:
    if args.no_heldout:
        report.skip("held-out", "disabled by --no-heldout")
        return {}
    missing = [path for path in (args.eval, args.examples, args.index)
               if not path.is_file()]
    if missing:
        status = report.fail if args.require_heldout else report.skip
        status("held-out", "missing " + ", ".join(str(path) for path in missing))
        return {}
    try:
        evaluator = load_evaluator()
    except Exception as error:  # pragma: no cover - import failure path
        report.fail("held-out", f"cannot load scripts/evaluate_retrieval.py: {error}")
        return {}

    try:
        examples = evaluator.read_examples(args.examples)
        items = evaluator.eval_rows(args.eval)
        if args.limit:
            items = items[:args.limit]
        lemma_index = evaluator.load_lemma_index(args.index, required=True)
        extracted = [evaluator.extract_row(examples, item, lemma_index)
                     for item in items]
    except (FileNotFoundError, ValueError, SystemExit) as error:
        report.fail("held-out extraction", str(error))
        return {}

    categories: Counter[str] = Counter()
    extras: dict[str, dict[str, Any]] = {}
    matcher = evaluator.NameMatcher(names)
    for row in extracted:
        in_corpus = [name for name in row["global"] if matcher.contains(name)]
        out_of_corpus = [name for name in row["global"] if name not in in_corpus]
        row["gold"] = in_corpus
        row["out_of_corpus"] = out_of_corpus
        extras[row["row"]["example_id"]] = row
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
    report.pass_("held-out extraction",
                 f"{len(extracted)} rows, {len(applicable)} with an in-corpus "
                 f"target reference")
    if not applicable:
        report.warn("held-out coverage",
                    "no applicable rows; retrieval recall is undefined")

    sample = evenly_spaced(applicable, args.sample)
    by_retriever: dict[str, Any] = {}
    for label, retriever in retrievers.items():
        per_row = evaluator.evaluate(
            sample, retriever, matcher, module_names,
            exclude_module=False, query_key="goal_target", k=20)
        for row in per_row:
            row["out_of_corpus"] = extras.get(row["example_id"], {}).get(
                "out_of_corpus", [])
        by_retriever[label] = {
            "summary": evaluator.summarize(per_row),
            "rows": per_row,
        }

    report.heading("held-out sanity")
    report.line(f"applicable rows: {len(applicable)}/{len(extracted)}; "
                f"sampled {len(sample)} evenly spaced")
    report.line("diagnostic subset only; run scripts/evaluate_retrieval.py "
                "for the full report")
    report.line(f"{'retriever':10s} {'@1':>7s} {'@5':>7s} {'@10':>7s} {'@20':>7s}")
    for label, section in by_retriever.items():
        table = section["summary"]["recall_rows"]
        report.line(f"{label:10s} {table['1']:7.1%} {table['5']:7.1%} "
                    f"{table['10']:7.1%} {table['20']:7.1%}")
    for label, section in by_retriever.items():
        families = section["summary"]["by_family"]
        if not families:
            continue
        report.line(f"{label} by family:")
        for family, row in families.items():
            table = row["recall_rows"]
            report.line(f"  {family:14s} n={row['rows']:3d} "
                        f"@1={table['1']:5.1%} @5={table['5']:5.1%} "
                        f"@10={table['10']:5.1%} @20={table['20']:5.1%}")
    if not args.no_rows:
        for label, section in by_retriever.items():
            report.line(f"{label} sampled rows:")
            for row in section["rows"]:
                gold = ", ".join(name.rsplit(".", 1)[-1]
                                 for name in row["gold"][:4])
                top = ", ".join(name.rsplit(".", 1)[-1]
                                for name in row["top10"][:5])
                report.line(f"  {row['example_id']} [{row['family']}] "
                            f"hit@20={row['row_hit'][20]} gold={gold} "
                            f"top5={top}")

    return {
        "applicable_rows": len(applicable),
        "total_rows": len(extracted),
        "categories": dict(sorted(categories.items())),
        "sampled_rows": len(sample),
        "retrievers": by_retriever,
    }


def compare_report(args: argparse.Namespace, report: Report,
                   heldout: dict[str, Any]) -> dict[str, Any]:
    if args.compare_report is None:
        return {}
    path = args.compare_report
    if not path.is_file():
        report.warn("compare", f"report not found: {path}")
        return {}
    try:
        committed = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        report.fail("compare", f"{path} is not valid JSON: {error}")
        return {}
    mapping = {"lexical": "name_and_type", "dense": "dense", "hybrid": "hybrid"}
    comparisons: dict[str, Any] = {}
    for label, section in heldout.get("retrievers", {}).items():
        committed_section = committed.get(mapping[label])
        if not committed_section:
            report.warn("compare", f"{path} has no {mapping[label]} section")
            continue
        expected = {row["example_id"]: row
                    for row in committed_section.get("rows", [])}
        mismatches = []
        for row in section["rows"]:
            other = expected.get(row["example_id"])
            if other is None:
                mismatches.append({"example_id": row["example_id"],
                                   "reason": "missing from the committed report"})
            elif row["top10"] != other.get("top10"):
                mismatches.append({"example_id": row["example_id"],
                                   "reason": "top-10 differs"})
        if mismatches:
            status = report.fail if args.strict_compare else report.warn
        else:
            status = report.pass_
        status(f"compare {label}",
               f"{len(mismatches)}/{len(section['rows'])} sampled rows differ")
        comparisons[label] = {"mismatches": len(mismatches),
                              "examples": mismatches[:5]}
    return comparisons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--corpus-meta", type=Path,
                        help="corpus provenance; defaults to <corpus>.meta.json")
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--embedding-meta", type=Path,
                        help="defaults to <embeddings>.meta.json")
    parser.add_argument("--examples", type=Path, default=DEFAULT_EXAMPLES)
    parser.add_argument("--eval", type=Path, default=DEFAULT_EVAL)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--retriever", action="append", choices=RETRIEVERS,
                        help="repeatable; default all available retrievers")
    parser.add_argument("--no-dense", action="store_true",
                        help="skip the embedding cache and model entirely")
    parser.add_argument("--no-heldout", action="store_true",
                        help="skip the held-out sanity run")
    parser.add_argument("--require-dense", action="store_true",
                        help="turn a skipped dense path into a failure")
    parser.add_argument("--require-heldout", action="store_true",
                        help="turn a skipped held-out run into a failure")
    parser.add_argument("--sample", type=int, default=20,
                        help="applicable rows in the held-out sanity run (0 = all)")
    parser.add_argument("--limit", type=int, default=0,
                        help="evaluate only the first N held-out rows (0 = all)")
    parser.add_argument("--k", type=int, default=10,
                        help="candidates per custom query and smoke probe")
    parser.add_argument("--query", action="append", default=[],
                        help="extra query to inspect; repeatable")
    parser.add_argument("--no-rows", action="store_true",
                        help="hide per-row held-out details")
    parser.add_argument("--skip-digests", action="store_true",
                        help="skip corpus and matrix SHA-256 checks")
    parser.add_argument("--full-integrity", action="store_true",
                        help="check every embedding row, not a 1024-row sample")
    parser.add_argument("--dense-model")
    parser.add_argument("--dense-revision")
    parser.add_argument("--dense-pooling", choices=("mean", "cls"))
    parser.add_argument("--dense-max-length", type=int)
    parser.add_argument("--dense-batch-size", type=int, default=128)
    parser.add_argument("--dense-threads", type=int, default=0)
    parser.add_argument("--hybrid-depth", type=int, default=50)
    parser.add_argument("--rrf-k", type=float, default=60.0)
    parser.add_argument("--compare-report", type=Path, default=None)
    parser.add_argument("--strict-compare", action="store_true",
                        help="make report mismatches failures instead of warnings")
    parser.add_argument("--output", type=Path,
                        help="write the JSON report here")
    parser.add_argument("--json", nargs="?", const=True, default=False,
                        metavar="PATH",
                        help="print the JSON report; with PATH, also write it there")
    args = parser.parse_args(argv)

    report = Report()
    report.protocol = {
        "corpus": str(args.corpus),
        "retrievers_requested": args.retriever or list(RETRIEVERS),
        "query": "goal target after the turnstile (primary)",
        "matching": "relaxed name match (qualified suffix or basename)",
        "sample_method": "evenly spaced over applicable rows",
        "caveat": "recall is a diagnostic; Lean is the authority for proof acceptance",
        "digests_checked": not args.skip_digests,
    }

    if not args.corpus.is_file():
        report.fail("corpus", f"not found: {args.corpus}")
        return finish(report, args)

    corpus_sha = None if args.skip_digests else sha256_file(args.corpus)
    built = build_lexical(args.corpus, report)
    if built is None:
        return finish(report, args)
    total, names, bm25, module_names, probes = built
    check_corpus_meta(args.corpus, total,
                      corpus_sha, args.corpus_meta or derived_corpus_meta(args.corpus),
                      report)

    dense_state = setup_dense(args, args.corpus, total, corpus_sha, names, report)
    retrievers: dict[str, Any] = {"lexical": bm25}
    if dense_state is not None:
        from neuralproof.embeddings import RRFRetriever
        retrievers["dense"] = dense_state["index"]
        retrievers["hybrid"] = RRFRetriever(
            [bm25, dense_state["index"]], depth=args.hybrid_depth,
            k=args.rrf_k)
        report.pass_("hybrid index",
                     f"RRF depth {args.hybrid_depth}, k={args.rrf_k}, equal weights")

    selected = args.retriever or list(retrievers)
    missing = [label for label in selected if label not in retrievers]
    for label in missing:
        report.warn("retriever",
                    f"{label} requested but unavailable; see the dense checks")
    selected = [label for label in selected if label in retrievers]
    if not selected:
        report.fail("retrievers", "none of the requested retrievers are available")
        return finish(report, args)
    selected_retrievers = {label: retrievers[label] for label in selected}
    report.protocol["retrievers_run"] = selected

    report.heading("index smoke")
    smoke = check_self_retrieval(selected_retrievers, probes, report, args.k)
    if probes:
        report.pass_("probes", f"{len(probes)} declaration statements")
    else:
        report.warn("probes", "no probe statements selected")

    custom = []
    if args.query:
        report.heading("custom queries")
        custom = run_custom_queries(selected_retrievers, args.query, report, args.k)

    heldout = run_heldout(args, report, selected_retrievers, names, module_names)
    comparisons = compare_report(args, report, heldout)

    report.data = {
        "smoke": {"corpus_rows": total, "probes": smoke},
        "custom_queries": custom,
        "heldout": heldout,
        "comparison": comparisons,
    }
    return finish(report, args)


def finish(report: Report, args: argparse.Namespace) -> int:
    payload = {
        "protocol": report.protocol,
        "checks": report.checks,
        "failures": report.failures,
        "warnings": report.warnings,
        **report.data,
    }
    # ``--json PATH`` is convenient for a one-command run; ``--output`` is the
    # explicit write-only option and wins if both are given.
    json_path = Path(args.json) if isinstance(args.json, str) else None
    output = args.output or json_path
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n")
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("\n".join(report.lines))
        if report.failures:
            print(f"\nFAIL: {report.failures} check(s) failed; "
                  f"{report.warnings} warning(s)")
        else:
            print(f"\nPASS: checked invariants hold; {report.warnings} warning(s)")
        if output:
            print(f"Report written to {output}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
