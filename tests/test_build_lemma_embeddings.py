"""The resumable embedding builder, exercised with a deterministic fake encoder.

These tests never download a model or import torch.  They pin the cache
contract the evaluator relies on: row alignment with the corpus, normalized
rows, resumable progress, and provenance that identifies the inputs.
"""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_builder():
    path = REPO_ROOT / "scripts" / "build_lemma_embeddings.py"
    spec = importlib.util.spec_from_file_location("build_lemma_embeddings", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = _load_builder()


class FakeEncoder:
    """Deterministic per-text vectors, so batches can be compared directly."""

    DIM = 16
    instances = []

    def __init__(self, model, revision=None, *, pooling="mean", max_length=128,
                 batch_size=128, threads=0, quantize=False):
        self.model = model
        self.revision = revision
        self.pooling = pooling
        self.max_length = max_length
        self.batch_size = batch_size
        self.quantize = quantize
        self.dimension = self.DIM
        self.encoded_texts = []
        self.calls = 0
        self.__class__.instances.append(self)

    @classmethod
    def vector(cls, text):
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = np.frombuffer(digest[:cls.DIM], dtype=np.uint8).astype(np.float32)
        raw += 1.0
        return raw / np.linalg.norm(raw)

    def encode_batches(self, texts):
        batch = []
        for text in texts:
            batch.append(text)
            if len(batch) >= self.batch_size:
                yield self._encode(batch)
                batch = []
        if batch:
            yield self._encode(batch)

    def _encode(self, batch):
        self.calls += 1
        self.encoded_texts.extend(batch)
        return np.vstack([self.vector(text) for text in batch])


DOCS = [
    {"name": "Foo.one", "kind": "theorem", "type": "1 = 1", "module": "Mathlib.Foo"},
    {"name": "Foo.two", "kind": "theorem", "type": "2 = 2", "module": "Mathlib.Foo"},
    {"name": "Bar.three", "kind": "theorem", "type": "3 = 3", "module": "Mathlib.Bar"},
]


def write_corpus(path, documents=DOCS):
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for document in documents:
            stream.write(json.dumps(document) + "\n")
    return path


def texts_of(documents=DOCS):
    return [f"{row['name']} {row['type']}" for row in documents]


@pytest.fixture
def fake_builder(monkeypatch):
    FakeEncoder.instances = []
    monkeypatch.setattr(builder, "EmbeddingEncoder", FakeEncoder)
    # Keep metadata deterministic and avoid three git subprocesses per test.
    monkeypatch.setattr(builder, "code_revision", lambda: "test-revision")
    monkeypatch.setattr(builder, "working_tree_state", lambda: "clean")
    monkeypatch.setattr(builder, "code_diff_sha256", lambda: "0" * 64)
    return builder


def run_builder(corpus, output, meta, *extra):
    return builder.main([
        "--corpus", str(corpus),
        "--output", str(output),
        "--meta", str(meta),
        *extra,
    ])


def test_build_writes_row_aligned_normalized_matrix_and_meta(
        tmp_path, fake_builder):
    corpus = write_corpus(tmp_path / "corpus.jsonl.gz")
    output = tmp_path / "emb.npy"
    meta = tmp_path / "emb.meta.json"

    assert run_builder(corpus, output, meta) == 0

    matrix = np.load(output)
    assert matrix.shape == (3, FakeEncoder.DIM)
    assert matrix.dtype == np.float32
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-6)
    assert np.allclose(matrix, np.vstack([FakeEncoder.vector(text)
                                          for text in texts_of()]))

    metadata = json.loads(meta.read_text())
    assert metadata["artifact"] == "lemma_statement_embeddings"
    assert metadata["rows"] == 3
    assert metadata["dim"] == FakeEncoder.DIM
    assert metadata["model"] == builder.DEFAULT_MODEL
    assert metadata["revision"] == builder.DEFAULT_REVISION
    assert metadata["normalized"] is True
    assert metadata["output_sha256"] == builder.sha256_file(output)
    assert metadata["corpus_sha256"] == builder.sha256_file(corpus)
    assert metadata["code_revision"] == "test-revision"
    assert metadata["code_state"] == "clean"
    assert not builder.progress_path(output).exists()


def test_build_returns_cached_without_constructing_another_encoder(
        tmp_path, fake_builder, capsys):
    corpus = write_corpus(tmp_path / "corpus.jsonl.gz")
    output = tmp_path / "emb.npy"
    meta = tmp_path / "emb.meta.json"
    assert run_builder(corpus, output, meta) == 0
    capsys.readouterr()

    assert run_builder(corpus, output, meta) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "cached"
    assert len(FakeEncoder.instances) == 1


def test_build_resumes_from_progress_and_encodes_only_the_remainder(
        tmp_path, fake_builder):
    corpus = write_corpus(tmp_path / "corpus.jsonl.gz")
    output = tmp_path / "emb.npy"
    meta = tmp_path / "emb.meta.json"
    progress = builder.progress_path(output)
    texts = texts_of()

    # Seed a completed prefix and a matching progress record.
    prefix = np.vstack([FakeEncoder.vector(text) for text in texts[:2]])
    matrix = np.lib.format.open_memmap(
        output, mode="w+", dtype="float32",
        shape=(len(texts), FakeEncoder.DIM))
    matrix[:2] = prefix
    matrix.flush()
    del matrix
    progress.write_text(json.dumps({
        "corpus": str(corpus),
        "corpus_sha256": builder.sha256_file(corpus),
        "model": builder.DEFAULT_MODEL,
        "revision": builder.DEFAULT_REVISION,
        "pooling": "mean",
        "max_length": 128,
        "batch_size": 128,
        "quantize": False,
        "normalized": True,
        "rows": len(texts),
        "dim": FakeEncoder.DIM,
        "rows_done": 2,
    }, indent=2))

    assert run_builder(corpus, output, meta) == 0

    assert FakeEncoder.instances[-1].encoded_texts == texts[2:]
    final = np.load(output)
    assert np.allclose(final, np.vstack([FakeEncoder.vector(text)
                                         for text in texts]))
    metadata = json.loads(meta.read_text())
    assert metadata["rows"] == len(texts)
    assert not progress.exists()


def test_build_restarts_when_the_progress_configuration_differs(
        tmp_path, fake_builder):
    corpus = write_corpus(tmp_path / "corpus.jsonl.gz")
    output = tmp_path / "emb.npy"
    meta = tmp_path / "emb.meta.json"
    progress = builder.progress_path(output)
    texts = texts_of()

    matrix = np.lib.format.open_memmap(
        output, mode="w+", dtype="float32",
        shape=(len(texts), FakeEncoder.DIM))
    matrix[:2] = np.vstack([FakeEncoder.vector(text) for text in texts[:2]])
    matrix.flush()
    del matrix
    progress.write_text(json.dumps({
        "corpus": str(corpus),
        "corpus_sha256": builder.sha256_file(corpus),
        "model": builder.DEFAULT_MODEL,
        "revision": builder.DEFAULT_REVISION,
        "pooling": "mean",
        "max_length": 64,  # differs from the run below
        "batch_size": 128,
        "quantize": False,
        "normalized": True,
        "rows": len(texts),
        "dim": FakeEncoder.DIM,
        "rows_done": 2,
    }, indent=2))

    assert run_builder(corpus, output, meta) == 0

    assert FakeEncoder.instances[-1].encoded_texts == texts
    assert np.allclose(np.load(output),
                       np.vstack([FakeEncoder.vector(text) for text in texts]))


def test_build_force_rebuilds_and_produces_the_same_matrix(
        tmp_path, fake_builder):
    corpus = write_corpus(tmp_path / "corpus.jsonl.gz")
    output = tmp_path / "emb.npy"
    meta = tmp_path / "emb.meta.json"
    assert run_builder(corpus, output, meta) == 0
    first = np.load(output).copy()

    assert run_builder(corpus, output, meta, "--force") == 0

    assert len(FakeEncoder.instances) == 2
    assert np.allclose(np.load(output), first)


def test_build_limit_embeds_only_the_prefix(tmp_path, fake_builder):
    corpus = write_corpus(tmp_path / "corpus.jsonl.gz")
    output = tmp_path / "emb.npy"
    meta = tmp_path / "emb.meta.json"

    assert run_builder(corpus, output, meta, "--limit", "2") == 0

    assert np.load(output).shape == (2, FakeEncoder.DIM)
    assert json.loads(meta.read_text())["rows"] == 2
    assert FakeEncoder.instances[-1].encoded_texts == texts_of()[:2]


def test_build_rejects_a_missing_corpus(tmp_path, fake_builder):
    with pytest.raises(SystemExit, match="corpus not found"):
        run_builder(tmp_path / "missing.jsonl.gz", tmp_path / "emb.npy",
                    tmp_path / "emb.meta.json")
