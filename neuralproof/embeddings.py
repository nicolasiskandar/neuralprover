"""Dense and hybrid retrieval over lemma statements.

The encoder is optional and imported lazily: the index and the hybrid fusion
are plain NumPy, so they can be tested without downloading a model.  As with
lexical retrieval, a returned name is only a candidate; Lean decides whether a
tactic that uses it is accepted.

Embeddings are L2-normalized, so cosine similarity is a dot product.  The
hybrid retriever fuses ranked lists with reciprocal rank fusion (RRF), which
needs no score calibration between the lexical and dense indexes.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Iterator, Sequence

import numpy as np


def mean_pool(hidden: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Average token vectors, ignoring padding."""
    mask = attention_mask[..., None].astype(np.float32)
    return (hidden * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1.0)


def cls_pool(hidden: np.ndarray) -> np.ndarray:
    """Take the first token, the pooling used by the BGE family."""
    return hidden[:, 0]


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    """Return float32 rows with unit L2 norm (zero rows are left as zeros)."""
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


class EmbeddingEncoder:
    """Encode text with a Hugging Face transformer, lazily loaded.

    ``pooling`` is ``"mean"`` or ``"cls"``.  ``max_length`` truncates long
    statements; the corpus prefixes the lemma name, so truncation keeps the
    most identifying text.  ``quantize`` dynamically quantizes Linear layers
    for CPU inference and is recorded in the cache metadata.
    """

    def __init__(self, model: str, revision: str | None = None, *,
                 pooling: str = "mean", max_length: int = 128,
                 batch_size: int = 128, threads: int = 0,
                 device: str = "cpu", quantize: bool = False):
        if pooling not in {"mean", "cls"}:
            raise ValueError(f"unknown pooling {pooling!r}")
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as error:  # pragma: no cover - dependency error path
            raise RuntimeError(
                "dense retrieval needs torch and transformers; install the "
                "optional 'model' dependencies from pyproject.toml") from error
        self.torch = torch
        self.pooling = pooling
        self.max_length = max_length
        self.batch_size = batch_size
        if threads > 0:
            torch.set_num_threads(threads)
        self.tokenizer = AutoTokenizer.from_pretrained(model, revision=revision)
        self.model = AutoModel.from_pretrained(model, revision=revision).eval()
        if quantize:
            self.model = torch.quantization.quantize_dynamic(
                self.model, {torch.nn.Linear}, dtype=torch.qint8)

    @property
    def dimension(self) -> int:
        return int(self.model.config.hidden_size)

    def encode_batches(self, texts: Iterable[str]) -> Iterator[np.ndarray]:
        """Yield one normalized float32 matrix per batch."""
        batch: list[str] = []
        for text in texts:
            batch.append(text)
            if len(batch) >= self.batch_size:
                yield self._encode(batch)
                batch = []
        if batch:
            yield self._encode(batch)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Encode all texts into one normalized float32 matrix."""
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        return np.vstack(list(self.encode_batches(texts)))

    def _encode(self, batch: list[str]) -> np.ndarray:
        torch = self.torch
        tokens = self.tokenizer(batch, padding=True, truncation=True,
                                max_length=self.max_length, return_tensors="pt")
        with torch.inference_mode():
            hidden = self.model(**tokens).last_hidden_state
        mask = tokens["attention_mask"].numpy()
        vectors = (mean_pool(hidden.numpy(), mask) if self.pooling == "mean"
                   else cls_pool(hidden.numpy()))
        return normalize_rows(vectors)


class DenseIndex:
    """Exact nearest-neighbour search over normalized embeddings."""

    def __init__(self, names: Sequence[str], embeddings: np.ndarray, *,
                 encoder: EmbeddingEncoder | None = None,
                 normalize: bool = False):
        if embeddings.ndim != 2:
            raise ValueError("embeddings must be a 2-D matrix")
        if len(names) != embeddings.shape[0]:
            raise ValueError(
                f"{len(names)} names but {embeddings.shape[0]} embeddings")
        self.names = list(names)
        self.embeddings = (normalize_rows(embeddings) if normalize
                           else np.asarray(embeddings, dtype=np.float32))
        self.encoder = encoder
        self._query_cache: dict[str, np.ndarray] = {}
        self._score_cache: dict[str, np.ndarray] = {}
        self._name_to_id = {name: index for index, name in enumerate(self.names)}

    @property
    def size(self) -> int:
        return len(self.names)

    def query_vector(self, query: str) -> np.ndarray:
        cached = self._query_cache.get(query)
        if cached is None:
            if self.encoder is None:
                raise RuntimeError(
                    "a text query needs an encoder; construct the index with one")
            cached = self.encoder.encode([query])[0]
            self._query_cache[query] = cached
        return cached

    def search(self, query: str, k: int = 20, *,
               exclude: Iterable[str] = ()) -> list[tuple[str, float]]:
        """Return up to ``k`` ``(name, similarity)`` pairs, best first."""
        if k <= 0 or not self.names:
            return []
        # Several evaluations reuse the same query with different exclusions;
        # cache the similarity vector so the corpus is scored only once.
        scores = self._score_cache.get(query)
        if scores is None:
            scores = self.embeddings @ self.query_vector(query)
            self._score_cache[query] = scores
        excluded = [self._name_to_id[name] for name in exclude
                    if name in self._name_to_id]
        if excluded:
            scores = scores.copy()
            scores[excluded] = -np.inf
        if k >= len(scores):
            order = np.argsort(-scores, kind="stable")
        else:
            top = np.argpartition(-scores, k)[:k]
            order = top[np.argsort(-scores[top], kind="stable")]
        return [(self.names[index], float(scores[index]))
                for index in order[:k] if math.isfinite(float(scores[index]))]


class RRFRetriever:
    """Reciprocal rank fusion of several ranked retrievers.

    ``score(d) = sum_r weight_r / (k + rank_r(d))``.  ``k`` is the usual RRF
    damping constant and is fixed before evaluation; it is not tuned on the
    held-out targets.
    """

    def __init__(self, retrievers: Sequence[object], *,
                 weights: Sequence[float] | None = None,
                 depth: int = 50, k: float = 60.0):
        if not retrievers:
            raise ValueError("at least one retriever is required")
        if weights is None:
            weights = [1.0] * len(retrievers)
        if len(weights) != len(retrievers):
            raise ValueError("one weight per retriever is required")
        self.retrievers = list(retrievers)
        self.weights = [float(weight) for weight in weights]
        self.depth = depth
        self.k = k

    def search(self, query: str, k: int = 20, *,
               exclude: Iterable[str] = ()) -> list[tuple[str, float]]:
        scores: defaultdict[str, float] = defaultdict(float)
        for retriever, weight in zip(self.retrievers, self.weights):
            ranked = retriever.search(query, k=self.depth, exclude=exclude)
            for rank, (name, _) in enumerate(ranked, 1):
                scores[name] += weight / (self.k + rank)
        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return ordered[:k]
