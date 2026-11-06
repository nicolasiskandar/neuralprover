#!/usr/bin/env python3
"""Build a cached embedding matrix for the lemma-statement corpus.

The matrix is row-aligned with ``data/lemma_statements.jsonl.gz`` and is
L2-normalized, so retrieval is a dot product.  The build is resumable: a
``.progress.json`` beside the output records how many rows are complete, and a
restart continues from there.  The cache lives under ``data/cache/`` and is not
tracked; the evaluator copies the model, revision and output digest into the
committed report.

    python scripts/build_lemma_embeddings.py \
        --model sentence-transformers/all-MiniLM-L6-v2 \
        --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
        --output data/cache/lemma-embeddings/minilm-l6-v2.npy
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from neuralproof.data.provenance import (  # noqa: E402
    code_diff_sha256, code_revision, sha256_file, working_tree_state)
from neuralproof.embeddings import EmbeddingEncoder  # noqa: E402
from neuralproof.retrieval import iter_statements  # noqa: E402

DEFAULT_CORPUS = REPO_ROOT / "data" / "lemma_statements.jsonl.gz"
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
DEFAULT_OUTPUT = (REPO_ROOT / "data" / "cache" / "lemma-embeddings"
                  / "all-MiniLM-L6-v2.npy")


def progress_path(output: Path) -> Path:
    return output.with_suffix(".progress.json")


def configuration(args: argparse.Namespace, corpus_sha: str, total: int) -> dict:
    return {
        "corpus": str(args.corpus),
        "corpus_sha256": corpus_sha,
        "model": args.model,
        "revision": args.revision,
        "pooling": args.pooling,
        "max_length": args.max_length,
        "batch_size": args.batch_size,
        "quantize": args.quantize,
        "normalized": True,
        "rows": total,
    }


def load_progress(path: Path, expected: dict) -> dict | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    for key, value in expected.items():
        if raw.get(key) != value:
            return None
    return raw


def count_rows(corpus: Path) -> int:
    return sum(1 for _ in iter_statements(corpus))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--pooling", choices=("mean", "cls"), default="mean")
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--threads", type=int, default=0,
                        help="torch CPU threads; 0 keeps the torch default")
    parser.add_argument("--quantize", action="store_true",
                        help="dynamically quantize Linear layers for CPU")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--meta", type=Path,
                        help="defaults to <output>.meta.json")
    parser.add_argument("--limit", type=int, default=0,
                        help="embed only the first N rows (0 = all)")
    parser.add_argument("--force", action="store_true",
                        help="ignore an existing embedding matrix")
    args = parser.parse_args(argv)

    if not args.corpus.is_file():
        raise SystemExit(f"corpus not found: {args.corpus}")
    total = count_rows(args.corpus)
    if args.limit:
        total = min(total, args.limit)
    corpus_sha = sha256_file(args.corpus)
    expected = configuration(args, corpus_sha, total)
    meta_path = args.meta or args.output.with_suffix(".meta.json")
    progress_file = progress_path(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    if args.output.is_file() and not args.force and meta_path.is_file():
        meta = json.loads(meta_path.read_text())
        if all(meta.get(key) == value for key, value in expected.items()):
            print(json.dumps({"status": "cached", "output": str(args.output),
                              "rows": meta["rows"], "dim": meta["dim"]}, indent=2))
            return 0

    progress = None if args.force else load_progress(progress_file, expected)
    start = int(progress["rows_done"]) if progress else 0
    dim = int(progress["dim"]) if progress else 0
    if start > total:
        start, dim = 0, 0

    encoder = EmbeddingEncoder(
        args.model, args.revision, pooling=args.pooling,
        max_length=args.max_length, batch_size=args.batch_size,
        threads=args.threads, quantize=args.quantize)

    statements = islice(iter_statements(args.corpus), start, total)
    texts = (statement.document(include_type=True) for statement in statements)

    if start == 0:
        # The first batch fixes the dimension; then create the final .npy so a
        # crash leaves a resumable file rather than an orphaned part file.
        batches = encoder.encode_batches(texts)
        try:
            first = next(batches)
        except StopIteration:
            raise SystemExit("the corpus is empty; refusing to write embeddings")
        dim = int(first.shape[1])
        matrix = np.lib.format.open_memmap(
            args.output, mode="w+", dtype="float32", shape=(total, dim))
        matrix[0:first.shape[0]] = first
        start = int(first.shape[0])
    else:
        matrix = np.lib.format.open_memmap(args.output, mode="r+")
        if matrix.shape != (total, dim):
            raise SystemExit(
                f"{args.output} has shape {matrix.shape}, expected {(total, dim)}")
        batches = encoder.encode_batches(texts)

    matrix.flush()
    progress_file.write_text(json.dumps({**expected, "dim": dim,
                                         "rows_done": start}, indent=2) + "\n")
    for batch in batches:
        if start + batch.shape[0] > total:
            batch = batch[:total - start]
        matrix[start:start + batch.shape[0]] = batch
        start += batch.shape[0]
        matrix.flush()
        progress_file.write_text(json.dumps(
            {**expected, "dim": dim, "rows_done": start}, indent=2) + "\n")
    del matrix

    if start != total:
        raise SystemExit(f"stopped after {start}/{total} rows; rerun to resume")

    metadata = {
        "artifact": "lemma_statement_embeddings",
        "schema_version": 1,
        "command": " ".join(["python", str(Path(__file__).relative_to(REPO_ROOT))]
                            + sys.argv[1:]),
        **expected,
        "dim": dim,
        "dtype": "float32",
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "code_revision": code_revision(),
        "code_state": working_tree_state(),
        "code_diff_sha256": code_diff_sha256(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "caveats": [
            "embeddings are retrieval input, not proof evidence",
            "a nearest neighbour is not a lemma application; Lean is the authority",
        ],
    }
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
    progress_file.unlink(missing_ok=True)
    print(json.dumps({
        "status": "built",
        "output": str(args.output),
        "meta": str(meta_path),
        "rows": total,
        "dim": dim,
        "output_sha256": metadata["output_sha256"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
