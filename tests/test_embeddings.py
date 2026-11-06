"""Dense retrieval: pooling, exact search, exclusion, and RRF fusion.

These use hand-written vectors, so they run without torch or a downloaded
model.  They check the ranking mechanics, not embedding quality; whether a
retrieved lemma applies is still a Lean question.
"""
import numpy as np
import pytest

from neuralproof.embeddings import (
    DenseIndex,
    RRFRetriever,
    cls_pool,
    mean_pool,
    normalize_rows,
)


class _Encoder:
    """A deterministic stand-in for a text encoder."""

    def __init__(self, vectors):
        self.vectors = vectors

    def encode(self, texts):
        return np.vstack([self.vectors[text] for text in texts])


def test_mean_pool_ignores_padding_and_cls_pool_takes_the_first_token():
    hidden = np.array([[[1.0, 1.0], [3.0, 3.0], [100.0, 100.0]]])
    mask = np.array([[1, 1, 0]])
    assert np.allclose(mean_pool(hidden, mask), [[2.0, 2.0]])
    assert np.allclose(cls_pool(hidden), [[1.0, 1.0]])


def test_normalize_rows_gives_unit_vectors_and_keeps_zero_rows():
    matrix = np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32)
    normalized = normalize_rows(matrix)
    assert np.allclose(normalized[0], [0.6, 0.8])
    assert np.allclose(normalized[1], [0.0, 0.0])


def test_dense_search_orders_by_similarity_and_breaks_ties_by_name():
    index = DenseIndex(
        ["Alpha.one", "Beta.two", "Gamma.three"],
        np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]]),
        encoder=_Encoder({"q": np.array([1.0, 0.0])}),
    )
    assert [name for name, _ in index.search("q", k=2)] == [
        "Alpha.one", "Beta.two"]
    # The corpus is sorted by name, so equal scores keep the earlier name.
    flat = DenseIndex(
        ["Alpha.one", "Beta.two"],
        np.array([[1.0, 0.0], [1.0, 0.0]]),
        encoder=_Encoder({"q": np.array([1.0, 0.0])}),
    )
    assert [name for name, _ in flat.search("q", k=2)] == [
        "Alpha.one", "Beta.two"]


def test_dense_search_excludes_names_and_returns_nothing_for_zero_k():
    index = DenseIndex(
        ["Alpha.one", "Beta.two"],
        np.array([[1.0, 0.0], [0.9, 0.1]]),
        encoder=_Encoder({"q": np.array([1.0, 0.0])}),
    )
    assert index.search("q", k=1, exclude={"Alpha.one"})[0][0] == "Beta.two"
    assert index.search("q", k=1, exclude={"Alpha.one", "Beta.two"}) == []
    assert index.search("q", k=0) == []


def test_dense_search_scores_a_repeated_query_once():
    class _CountingEncoder(_Encoder):
        def __init__(self, vectors):
            super().__init__(vectors)
            self.calls = 0

        def encode(self, texts):
            self.calls += 1
            return super().encode(texts)

    encoder = _CountingEncoder({"q": np.array([1.0, 0.0])})
    index = DenseIndex(
        ["Alpha.one", "Beta.two"],
        np.array([[1.0, 0.0], [0.9, 0.1]]),
        encoder=encoder,
    )
    assert index.search("q", k=2) == index.search("q", k=2)
    assert index.search("q", k=1, exclude={"Alpha.one"})[0][0] == "Beta.two"
    assert encoder.calls == 1


def test_dense_index_rejects_mismatched_names_and_embeddings():
    with pytest.raises(ValueError, match="2 names but 1 embeddings"):
        DenseIndex(["a", "b"], np.array([[1.0, 0.0]]))


def test_dense_index_can_normalize_unscaled_embeddings():
    index = DenseIndex(
        ["Alpha.one", "Beta.two"],
        np.array([[3.0, 0.0], [0.0, 4.0]]),
        encoder=_Encoder({"q": np.array([1.0, 0.0])}),
        normalize=True,
    )
    assert np.allclose(np.linalg.norm(index.embeddings, axis=1), [1.0, 1.0])
    assert [name for name, _ in index.search("q", k=2)] == [
        "Alpha.one", "Beta.two"]


def test_dense_search_k_larger_than_the_corpus_returns_every_candidate():
    index = DenseIndex(
        ["Alpha.one", "Beta.two"],
        np.array([[1.0, 0.0], [0.0, 1.0]]),
        encoder=_Encoder({"q": np.array([1.0, 0.0])}),
    )
    assert [name for name, _ in index.search("q", k=50)] == [
        "Alpha.one", "Beta.two"]


def test_embedding_encoder_rejects_unknown_pooling_before_loading_a_model():
    from neuralproof.embeddings import EmbeddingEncoder

    with pytest.raises(ValueError, match="unknown pooling"):
        EmbeddingEncoder("does-not-exist", pooling="max")


def test_dense_index_requires_an_encoder_for_text_queries():
    index = DenseIndex(["a"], np.array([[1.0, 0.0]]))
    with pytest.raises(RuntimeError, match="needs an encoder"):
        index.search("q", k=1)


class _StaticRetriever:
    def __init__(self, ranking):
        self.ranking = ranking

    def search(self, query, k=20, *, exclude=()):
        return [(name, 1.0) for name in self.ranking if name not in exclude][:k]


def test_rrf_combines_ranks_and_prefers_agreement():
    lexical = _StaticRetriever(["A", "B", "C"])
    dense = _StaticRetriever(["B", "A", "D"])
    hybrid = RRFRetriever([lexical, dense], depth=3, k=60.0)
    assert [name for name, _ in hybrid.search("q", k=3)] == ["A", "B", "C"]


def test_rrf_can_weight_a_retriever_and_honours_exclusion():
    lexical = _StaticRetriever(["A", "B"])
    dense = _StaticRetriever(["B", "A"])
    hybrid = RRFRetriever([lexical, dense], weights=[2.0, 1.0], depth=2)
    assert [name for name, _ in hybrid.search("q", k=2)] == ["A", "B"]
    assert [name for name, _ in hybrid.search("q", k=2, exclude={"A"})] == ["B"]


def test_rrf_requires_matching_weights():
    with pytest.raises(ValueError, match="one weight per retriever"):
        RRFRetriever([_StaticRetriever(["A"])], weights=[1.0, 2.0])


def test_rrf_requires_at_least_one_retriever():
    with pytest.raises(ValueError, match="at least one retriever"):
        RRFRetriever([])


def test_rrf_ignores_candidates_beyond_the_depth():
    deep = _StaticRetriever(["A", "B", "C"])
    shallow = _StaticRetriever(["C", "B", "A"])
    fused = RRFRetriever([deep, shallow], depth=1)
    # Only the first candidate from each list contributes; the others get no
    # score at all, so they cannot appear in the fused ranking.
    assert [name for name, _ in fused.search("q", k=3)] == ["A", "C"]


def test_rrf_breaks_equal_scores_by_name():
    first = _StaticRetriever(["B"])
    second = _StaticRetriever(["A"])
    fused = RRFRetriever([first, second])
    assert [name for name, _ in fused.search("q", k=2)] == ["A", "B"]
