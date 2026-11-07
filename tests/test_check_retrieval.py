"""The end-to-end retrieval checker, exercised on a tiny fake corpus.

The checker must validate the same cache contract as the evaluator and fail
loudly on inconsistent inputs.  These tests never download a model; the dense
path uses a deterministic fake encoder and a matching fake matrix.
"""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

import neuralproof.embeddings as embeddings_module

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_checker():
    path = REPO_ROOT / "scripts" / "check_retrieval.py"
    spec = importlib.util.spec_from_file_location("check_retrieval", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


checker = _load_checker()

DIM = 8

DOCUMENTS = [
    {"name": "Alpha.zero", "kind": "theorem", "type": "0 = 0",
     "module": "Mathlib.Alpha"},
    {"name": "Alpha.succ", "kind": "theorem", "type": "Nat.succ n = n + 1",
     "module": "Mathlib.Alpha"},
    {"name": "Beta.add_comm", "kind": "theorem", "type": "a + b = b + a",
     "module": "Mathlib.Beta"},
    {"name": "Gamma.mul_one", "kind": "theorem", "type": "a * 1 = a",
     "module": "Mathlib.Gamma"},
]


def document_text(document):
    return f"{document['name']} {document['type']}"


def vector(text):
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = np.frombuffer(digest[:DIM], dtype=np.uint8).astype(np.float32) + 1.0
    return raw / np.linalg.norm(raw)


class FakeEncoder:
    """A deterministic encoder that reproduces the fake cache rows exactly."""

    def __init__(self, model, revision=None, *, pooling="mean", max_length=128,
                 batch_size=128, threads=0):
        self.dimension = DIM

    def encode(self, texts):
        return np.vstack([vector(text) for text in texts])


@pytest.fixture
def fake_encoder(monkeypatch):
    monkeypatch.setattr(embeddings_module, "EmbeddingEncoder", FakeEncoder)


def write_corpus(tmp_path, documents=DOCUMENTS):
    corpus = tmp_path / "corpus.jsonl.gz"
    with gzip.open(corpus, "wt", encoding="utf-8") as stream:
        for document in documents:
            stream.write(json.dumps(document) + "\n")
    meta = tmp_path / "corpus.meta.json"
    meta.write_text(json.dumps({
        "output_sha256": checker.sha256_file(corpus),
        "output_count": len(documents),
    }))
    return corpus, meta


def write_cache(tmp_path, corpus, documents=DOCUMENTS, *, rows=None,
                output_sha256=None, corpus_sha256=None):
    matrix = np.vstack([vector(document_text(document)) for document in documents])
    embeddings = tmp_path / "emb.npy"
    np.save(embeddings, matrix.astype(np.float32))
    meta = tmp_path / "emb.meta.json"
    meta.write_text(json.dumps({
        "corpus_sha256": corpus_sha256 or checker.sha256_file(corpus),
        "model": "fake-model",
        "revision": "fake-revision",
        "pooling": "mean",
        "max_length": 128,
        "batch_size": 128,
        "quantize": False,
        "normalized": True,
        "rows": len(documents) if rows is None else rows,
        "dim": DIM,
        "dtype": "float32",
        "output_sha256": output_sha256 or checker.sha256_file(embeddings),
    }))
    return embeddings, meta


def write_heldout(tmp_path):
    index = tmp_path / "index.json"
    index.write_text(json.dumps([document["name"] for document in DOCUMENTS]))
    examples = tmp_path / "examples.jsonl"
    with examples.open("w") as stream:
        stream.write(json.dumps({
            "example_id": "ex-alpha",
            "context": "n : Nat",
            "goal_state": "⊢ 0 = 0",
            "theorem": "Target.thm",
            "syntax_kind": "Lean.Parser.Tactic.rewriteSeq",
            "source_file": "Mathlib/Target.lean",
            "source_declaration": "Target.thm",
        }) + "\n")
    evaluation = tmp_path / "eval.json"
    evaluation.write_text(json.dumps({
        "lora": {"examples": [{
            "example_id": "ex-alpha",
            "target": "rw [Alpha.zero]",
            "prediction": "rw [Alpha.zero]",
            "exact_match": True,
        }]}
    }))
    return examples, evaluation, index


def run(args, capsys):
    code = checker.main([str(value) for value in args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def base_args(corpus, meta, *, heldout=False):
    args = ["--corpus", corpus, "--corpus-meta", meta,
            "--no-rows", "--json"]
    if not heldout:
        args.append("--no-heldout")
    return args


def payload(output):
    return json.loads(output)


def checks_by_name(payload_):
    return {check["name"]: check for check in payload_["checks"]}


def test_lexical_check_passes_and_reports_self_retrieval(tmp_path, capsys):
    corpus, meta = write_corpus(tmp_path)

    code, output, _ = run(base_args(corpus, meta) + ["--no-dense"], capsys)

    assert code == 0
    report = payload(output)
    assert report["failures"] == 0
    checks = checks_by_name(report)
    assert checks["corpus"]["status"] == "pass"
    assert checks["corpus digest"]["status"] == "pass"
    assert checks["bm25 index"]["status"] == "pass"
    assert checks["dense"]["status"] == "skip"
    assert report["smoke"]["corpus_rows"] == len(DOCUMENTS)
    assert report["smoke"]["probes"]
    assert all(probe["ok"] for probe in report["smoke"]["probes"])


def test_corpus_digest_mismatch_fails(tmp_path, capsys):
    corpus, meta = write_corpus(tmp_path)
    meta.write_text(json.dumps({
        "output_sha256": "0" * 64,
        "output_count": len(DOCUMENTS),
    }))

    code, output, _ = run(base_args(corpus, meta) + ["--no-dense"], capsys)

    assert code == 1
    report = payload(output)
    assert checks_by_name(report)["corpus digest"]["status"] == "fail"


def test_corpus_row_count_mismatch_fails(tmp_path, capsys):
    corpus, meta = write_corpus(tmp_path)
    meta.write_text(json.dumps({
        "output_sha256": checker.sha256_file(corpus),
        "output_count": 99,
    }))

    code, output, _ = run(base_args(corpus, meta) + ["--no-dense"], capsys)

    assert code == 1
    assert checks_by_name(payload(output))["corpus rows"]["status"] == "fail"


def test_missing_dense_cache_is_an_explicit_skip(tmp_path, capsys):
    corpus, meta = write_corpus(tmp_path)
    missing = tmp_path / "missing.npy"

    code, output, _ = run(
        base_args(corpus, meta) + ["--embeddings", missing], capsys)

    assert code == 0
    report = payload(output)
    assert checks_by_name(report)["dense"]["status"] == "skip"
    assert "missing embedding cache" in checks_by_name(report)["dense"]["detail"]


def test_require_dense_turns_a_skip_into_a_failure(tmp_path, capsys):
    corpus, meta = write_corpus(tmp_path)
    missing = tmp_path / "missing.npy"

    code, output, _ = run(
        base_args(corpus, meta)
        + ["--embeddings", missing, "--require-dense"], capsys)

    assert code == 1
    assert checks_by_name(payload(output))["dense"]["status"] == "fail"


def test_dense_check_accepts_a_consistent_cache(tmp_path, capsys, fake_encoder):
    corpus, meta = write_corpus(tmp_path)
    embeddings, embedding_meta = write_cache(tmp_path, corpus)

    code, output, _ = run(
        base_args(corpus, meta)
        + ["--embeddings", embeddings, "--embedding-meta", embedding_meta],
        capsys)

    assert code == 0
    report = payload(output)
    checks = checks_by_name(report)
    assert checks["embedding rows"]["status"] == "pass"
    assert checks["embedding matrix digest"]["status"] == "pass"
    assert checks["embedding values"]["status"] == "pass"
    assert checks["dense encoder"]["status"] == "pass"
    assert checks["dense index"]["status"] == "pass"
    probes = [probe for probe in report["smoke"]["probes"]
              if probe["retriever"] == "dense"]
    assert probes and all(probe["ok"] for probe in probes)


def test_dense_cache_row_mismatch_fails(tmp_path, capsys, fake_encoder):
    corpus, meta = write_corpus(tmp_path)
    embeddings, embedding_meta = write_cache(tmp_path, corpus, rows=99)

    code, output, _ = run(
        base_args(corpus, meta)
        + ["--embeddings", embeddings, "--embedding-meta", embedding_meta],
        capsys)

    assert code == 1
    assert checks_by_name(payload(output))["embedding rows"]["status"] == "fail"


def test_dense_cache_matrix_digest_mismatch_fails(tmp_path, capsys, fake_encoder):
    corpus, meta = write_corpus(tmp_path)
    embeddings, embedding_meta = write_cache(
        tmp_path, corpus, output_sha256="0" * 64)

    code, output, _ = run(
        base_args(corpus, meta)
        + ["--embeddings", embeddings, "--embedding-meta", embedding_meta],
        capsys)

    assert code == 1
    assert checks_by_name(payload(output))["embedding matrix digest"]["status"] == "fail"


def test_dense_cache_built_from_another_corpus_fails(tmp_path, capsys,
                                                     fake_encoder):
    corpus, meta = write_corpus(tmp_path)
    embeddings, embedding_meta = write_cache(
        tmp_path, corpus, corpus_sha256="0" * 64)

    code, output, _ = run(
        base_args(corpus, meta)
        + ["--embeddings", embeddings, "--embedding-meta", embedding_meta],
        capsys)

    assert code == 1
    assert checks_by_name(payload(output))["embedding corpus digest"]["status"] == "fail"


def test_dense_metadata_missing_encoder_settings_fails(tmp_path, capsys,
                                                       fake_encoder):
    corpus, meta = write_corpus(tmp_path)
    embeddings, embedding_meta = write_cache(tmp_path, corpus)
    metadata = json.loads(embedding_meta.read_text())
    del metadata["model"]
    embedding_meta.write_text(json.dumps(metadata))

    code, output, _ = run(
        base_args(corpus, meta)
        + ["--embeddings", embeddings, "--embedding-meta", embedding_meta],
        capsys)

    assert code == 1
    assert checks_by_name(payload(output))["dense metadata"]["status"] == "fail"


def test_heldout_sanity_run_reports_recall(tmp_path, capsys):
    corpus, meta = write_corpus(tmp_path)
    examples, evaluation, index = write_heldout(tmp_path)

    code, output, _ = run(
        base_args(corpus, meta, heldout=True)
        + ["--no-dense", "--examples", examples, "--eval", evaluation,
           "--index", index],
        capsys)

    assert code == 0
    report = payload(output)
    heldout = report["heldout"]
    assert heldout["total_rows"] == 1
    assert heldout["applicable_rows"] == 1
    assert heldout["sampled_rows"] == 1
    assert heldout["categories"] == {"in_corpus": 1}
    assert heldout["retrievers"]["lexical"]["summary"]["applicable_rows"] == 1
    assert heldout["retrievers"]["lexical"]["summary"]["recall_rows"]["1"] == 1.0


def test_custom_query_is_included_in_the_report(tmp_path, capsys):
    corpus, meta = write_corpus(tmp_path)

    code, output, _ = run(
        base_args(corpus, meta)
        + ["--no-dense", "--query", "0 = 0"], capsys)

    assert code == 0
    report = payload(output)
    assert report["custom_queries"][0]["query"] == "0 = 0"
    assert report["custom_queries"][0]["results"]["lexical"]


def test_json_flag_accepts_an_output_path(tmp_path, capsys):
    corpus, meta = write_corpus(tmp_path)
    destination = tmp_path / "nested" / "check.json"

    code, output, _ = run(
        base_args(corpus, meta)
        + ["--no-dense", "--json", str(destination)], capsys)

    assert code == 0
    assert destination.is_file()
    assert payload(output)["failures"] == 0
    assert payload(destination.read_text())["failures"] == 0


def test_output_flag_writes_json_but_keeps_the_transcript(tmp_path, capsys):
    corpus, meta = write_corpus(tmp_path)
    destination = tmp_path / "check.json"

    code, output, _ = run(
        ["--corpus", str(corpus), "--corpus-meta", str(meta),
         "--no-heldout", "--no-rows", "--no-dense",
         "--output", str(destination)], capsys)

    assert code == 0
    assert destination.is_file()
    assert output.startswith("[PASS]")
    assert payload(destination.read_text())["failures"] == 0


def test_evenly_spaced_sample_is_deterministic():
    rows = list(range(10))
    assert checker.evenly_spaced(rows, 4) == [0, 3, 6, 9]
    assert checker.evenly_spaced(rows, 1) == [5]
    assert checker.evenly_spaced(rows, 20) == rows
    assert checker.evenly_spaced(rows, 0) == rows


def test_compare_report_warns_on_mismatch_by_default(tmp_path, capsys):
    corpus, meta = write_corpus(tmp_path)
    examples, evaluation, index = write_heldout(tmp_path)
    committed = tmp_path / "report.json"
    committed.write_text(json.dumps({
        "name_and_type": {"rows": [{
            "example_id": "ex-alpha",
            "top10": ["Gamma.mul_one"],
        }]}
    }))

    code, output, _ = run(
        base_args(corpus, meta, heldout=True)
        + ["--no-dense", "--examples", examples, "--eval", evaluation,
           "--index", index, "--compare-report", committed],
        capsys)

    assert code == 0
    report = payload(output)
    assert checks_by_name(report)["compare lexical"]["status"] == "warn"
    assert report["comparison"]["lexical"]["mismatches"] == 1


def test_strict_compare_turns_a_mismatch_into_a_failure(tmp_path, capsys):
    corpus, meta = write_corpus(tmp_path)
    examples, evaluation, index = write_heldout(tmp_path)
    committed = tmp_path / "report.json"
    committed.write_text(json.dumps({
        "name_and_type": {"rows": [{
            "example_id": "ex-alpha",
            "top10": [],
        }]}
    }))

    code, output, _ = run(
        base_args(corpus, meta, heldout=True)
        + ["--no-dense", "--examples", examples, "--eval", evaluation,
           "--index", index, "--compare-report", committed, "--strict-compare"],
        capsys)

    assert code == 1
    report = payload(output)
    assert checks_by_name(report)["compare lexical"]["status"] == "fail"
