"""The retrieval evaluation helpers: query normalization and name matching.

These cases pin the protocol decisions that the report depends on: the goal
target is the primary query, inaccessible-name markers are not terms, and
local or out-of-corpus references are not counted as retrieval failures.
"""
import importlib.util
import gzip
import json
import types
from pathlib import Path

import numpy as np
import pytest

import neuralproof.embeddings as embeddings_module
from neuralproof.retrieval import BM25Index

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_evaluator():
    path = REPO_ROOT / "scripts" / "evaluate_retrieval.py"
    spec = importlib.util.spec_from_file_location("evaluate_retrieval", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


evaluator = _load_evaluator()


def test_normalize_query_drops_inaccessible_markers_and_case_labels():
    goal = "\ncase succ\nx✝¹ : ℕ\nh✝ : True\n⊢ x✝ = 1"
    assert evaluator._normalize_query(goal) == "x : ℕ\nh : True\n⊢ x = 1"


def test_goal_target_is_the_expression_after_the_turnstile():
    goal = "x : ℕ\n⊢ x + 0 = x"
    assert evaluator._goal_target(goal) == "x + 0 = x"
    assert evaluator._goal_target("no turnstile") == "no turnstile"


def test_global_references_exclude_locals_and_resolve_suffixes():
    index = {"Mathlib.Foo.bar", "bar", "Baz.qux", "qux"}
    allowed = frozenset({"x", "Mathlib"})
    assert not evaluator.is_global_reference("x", index, allowed)
    assert not evaluator.is_global_reference("Mathlib.Foo.bar", index, allowed)
    assert evaluator.is_global_reference("Mathlib.Foo.bar", index, frozenset({"x"}))
    assert evaluator.is_global_reference("bar", index, frozenset({"x"}))
    assert evaluator.is_global_reference("Foo.bar", index, frozenset({"x"}))
    assert not evaluator.is_global_reference("missing", index, allowed)


def test_name_matcher_contains_exact_basename_and_suffix():
    matcher = evaluator.NameMatcher(["Mathlib.Foo.bar", "Baz.qux"])
    assert matcher.contains("Mathlib.Foo.bar")
    assert matcher.contains("Foo.bar")
    assert matcher.contains("bar")
    assert matcher.contains("qux")
    assert not matcher.contains("missing")


def test_name_matcher_strict_and_relaxed_suffix_rules():
    assert evaluator.NameMatcher.matches(
        "Mathlib.Foo.bar", "Foo.bar", strict=True)
    assert evaluator.NameMatcher.matches(
        "Foo.bar", "Mathlib.Foo.bar", strict=True)
    assert evaluator.NameMatcher.matches(
        "Mathlib.Foo.bar", "Other.bar", strict=False)
    assert not evaluator.NameMatcher.matches(
        "Mathlib.Foo.bar", "Other.bar", strict=True)


@pytest.mark.parametrize(("target", "syntax_kind", "expected"), [
    ("rw [foo]", "", "rw"),
    ("Prod.isUnit_iff", "Lean.Parser.Tactic.simp", "simp"),
    ("Foo.bar", "Lean.Parser.Tactic.allGoals", "all_goals"),
    ("Foo.bar", "Lean.Parser.Tactic.tacticRfl", "rfl"),
    ("Contact", "", "Contact"),
])
def test_target_family_uses_the_enclosing_tactic_for_bare_arguments(
        target, syntax_kind, expected):
    assert evaluator.target_family(target, syntax_kind) == expected


def _index():
    index = BM25Index()
    index.add("Foo.sum_comm", "sum comm")
    index.add("Foo.sum_assoc", "sum assoc")
    index.add("Bar.prod_comm", "prod comm")
    # Filler documents raise the corpus size so the default max-df filter keeps
    # ``sum`` (which occurs in two real candidates).  They share no query term.
    for number in range(17):
        index.add(f"Filler.n{number}", "unrelated filler")
    return index.finalize()


def _row(example_id, gold, query="sum assoc"):
    return {
        "row": {
            "example_id": example_id,
            "source_declaration": "Foo.sum_comm",
            "source_file": "Mathlib/Foo.lean",
        },
        "family": "rw",
        "query": query,
        "goal_target": query,
        "target_module": "Mathlib.Foo",
        "gold": gold,
        "local": [],
    }


def test_evaluate_reports_row_and_reference_hits():
    rows = evaluator.evaluate(
        [_row("ex", ["sum_assoc"])], _index(), evaluator.NameMatcher([]), {},
        exclude_module=False)
    row = rows[0]
    assert row["row_hit"] == {1: True, 5: True, 10: True, 20: True}
    assert row["reference_hits"] == {1: 1, 5: 1, 10: 1, 20: 1}
    assert row["strict_row_hit"][1] is True


def test_evaluate_can_exclude_the_targets_own_module():
    module_names = {"Mathlib.Foo": {"Foo.sum_comm", "Foo.sum_assoc"}}
    without_exclusion = evaluator.evaluate(
        [_row("ex", ["prod_comm"], query="sum assoc prod")], _index(),
        evaluator.NameMatcher([]), {}, exclude_module=False)
    with_exclusion = evaluator.evaluate(
        [_row("ex", ["prod_comm"], query="sum assoc prod")], _index(),
        evaluator.NameMatcher([]), module_names, exclude_module=True)

    assert without_exclusion[0]["row_hit"][1] is False
    assert with_exclusion[0]["row_hit"][1] is True


def test_summarize_counts_rows_and_references():
    rows = [
        {**_row("a", ["sum_assoc"]), "row_hit": {1: True, 5: True, 10: True, 20: True},
         "reference_hits": {1: 1, 5: 1, 10: 1, 20: 1},
         "strict_row_hit": {1: True, 5: True, 10: True, 20: True}},
        {**_row("b", ["missing"]), "row_hit": {1: False, 5: False, 10: False, 20: False},
         "reference_hits": {1: 0, 5: 0, 10: 0, 20: 0},
         "strict_row_hit": {1: False, 5: False, 10: False, 20: False}},
    ]
    summary = evaluator.summarize(rows)
    assert summary["applicable_rows"] == 2
    assert summary["gold_references"] == 2
    assert summary["recall_rows"]["1"] == pytest.approx(0.5)
    assert summary["recall_references"]["1"] == pytest.approx(0.5)
    assert summary["by_family"]["rw"]["rows"] == 2


DOCUMENTS = [
    {"name": "Foo.one", "kind": "theorem", "type": "1 = 1", "module": "Mathlib.Foo"},
    {"name": "Foo.two", "kind": "theorem", "type": "2 = 2", "module": "Mathlib.Foo"},
    {"name": "Bar.three", "kind": "theorem", "type": "3 = 3", "module": "Mathlib.Bar"},
]


class _FakeEncoder:
    """Query vectors chosen so the expected dense ranking is explicit."""

    DIM = 3

    def __init__(self, model, revision=None, *, pooling="mean", max_length=128,
                 batch_size=128, threads=0, quantize=False):
        self.dimension = self.DIM

    def encode(self, texts):
        vectors = []
        for text in texts:
            vectors.append({
                "one": [1.0, 0.0, 0.0],
                "two": [0.0, 1.0, 0.0],
            }.get(text, [0.0, 0.0, 1.0]))
        return np.asarray(vectors, dtype=np.float32)


def _write_corpus(tmp_path, documents=DOCUMENTS):
    path = tmp_path / "corpus.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for document in documents:
            stream.write(json.dumps(document) + "\n")
    return path


def _write_cache(tmp_path, corpus, documents=DOCUMENTS, *, dim=3,
                 meta_overrides=None):
    path = tmp_path / "emb.npy"
    matrix = np.zeros((len(documents), dim), dtype=np.float32)
    for index in range(len(documents)):
        matrix[index, index % dim] = 1.0
    np.save(path, matrix)
    metadata = {
        "corpus": str(corpus),
        "corpus_sha256": evaluator.sha256_file(corpus),
        "model": "fake-model",
        "revision": "fake-revision",
        "pooling": "mean",
        "max_length": 128,
        "batch_size": 128,
        "quantize": False,
        "normalized": True,
        "rows": len(documents),
        "dim": dim,
        "output_sha256": evaluator.sha256_file(path),
    }
    metadata.update(meta_overrides or {})
    meta_path = tmp_path / "emb.meta.json"
    meta_path.write_text(json.dumps(metadata))
    return path, meta_path


def _dense_args(embeddings, meta, corpus, **overrides):
    values = {
        "corpus": corpus,
        "embeddings": embeddings,
        "embedding_meta": meta,
        "dense_model": None,
        "dense_revision": None,
        "dense_pooling": None,
        "dense_max_length": None,
        "dense_batch_size": 8,
        "dense_threads": 0,
        "hybrid_depth": 50,
        "rrf_k": 60.0,
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


def _dense_row(example_id, gold, query, family="rw"):
    return {
        "row": {
            "example_id": example_id,
            "source_declaration": "Target.thm",
            "source_file": "Mathlib/Target.lean",
        },
        "family": family,
        "gold": gold,
        "local": [],
        "query": query,
        "goal_target": query,
        "context_query": "context " + query,
        "target_module": "Mathlib.Target",
    }


@pytest.fixture
def dense_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(embeddings_module, "EmbeddingEncoder", _FakeEncoder)
    corpus = _write_corpus(tmp_path)
    embeddings, meta = _write_cache(tmp_path, corpus)
    bm25, module_names = evaluator.build_index(corpus, include_type=True)
    names = [document["name"] for document in DOCUMENTS]
    rows = [
        _dense_row("ex-one", ["Foo.one"], "one"),
        _dense_row("ex-two", ["Foo.two"], "two", family="simp"),
    ]
    return {
        "corpus": corpus,
        "embeddings": embeddings,
        "meta": meta,
        "bm25": bm25,
        "module_names": module_names,
        "corpus_names": names,
        "matcher": evaluator.NameMatcher(names),
        "rows": rows,
    }


def run_dense(setup, **overrides):
    results = {"protocol": {}}
    evaluator.evaluate_dense_and_hybrid(
        results, _dense_args(setup["embeddings"], setup["meta"],
                             setup["corpus"], **overrides),
        setup["rows"], setup["matcher"], setup["module_names"],
        setup["bm25"], setup["corpus_names"])
    return results


def test_dense_and_hybrid_sections_are_added_with_recall(dense_setup):
    results = run_dense(dense_setup)

    for label in ("dense", "hybrid"):
        assert set(results[label]) >= {
            "primary", "full_goal", "context_goal", "same_module_excluded",
            "rows"}
        assert set(results[label]["primary"]["by_family"]) == {"rw", "simp"}
        for section in ("primary", "full_goal", "context_goal",
                        "same_module_excluded"):
            assert set(results[label][section]["recall_rows"]) == {
                "1", "5", "10", "20"}

    assert results["dense"]["corpus_documents"] == 3

    # The fake query vectors point directly at the gold declarations.
    assert results["dense"]["primary"]["recall_rows"]["1"] == 1.0
    assert results["hybrid"]["primary"]["recall_rows"]["1"] == 1.0
    assert results["dense"]["rows"][0]["gold"] == ["Foo.one"]


def test_dense_protocol_records_the_cache_and_hybrid_settings(dense_setup):
    results = run_dense(dense_setup)

    dense = results["protocol"]["dense"]
    assert dense["model"] == "fake-model"
    assert dense["revision"] == "fake-revision"
    assert dense["pooling"] == "mean"
    assert dense["max_length"] == 128
    assert dense["normalized"] is True
    assert dense["rows"] == 3
    assert dense["dim"] == 3
    assert dense["embedding_sha256"] == evaluator.sha256_file(
        dense_setup["embeddings"])
    assert dense["corpus_sha256"] == evaluator.sha256_file(
        dense_setup["corpus"])
    assert "fixed before evaluation" in dense["tuning"]

    hybrid = results["protocol"]["hybrid"]
    assert hybrid["fusion"] == "reciprocal rank fusion"
    assert hybrid["retrievers"] == ["bm25 name+type", "dense"]
    assert hybrid["weights"] == [1.0, 1.0]
    assert hybrid["depth"] == 50
    assert hybrid["rrf_k"] == 60.0
    assert "fixed before evaluation" in hybrid["tuning"]


@pytest.mark.parametrize(("overrides", "message"), [
    ({"corpus_sha256": "0" * 64}, "different corpus"),
    ({"rows": 2}, "row count does not match"),
    ({"output_sha256": "0" * 64}, "recorded digest"),
])
def test_dense_rejects_a_cache_that_does_not_match_the_corpus(
        dense_setup, tmp_path, overrides, message):
    corpus = dense_setup["corpus"]
    documents = DOCUMENTS
    embeddings, meta = _write_cache(tmp_path, corpus, documents,
                                    meta_overrides=overrides)
    dense_setup["embeddings"] = embeddings
    dense_setup["meta"] = meta

    with pytest.raises(SystemExit, match=message):
        run_dense(dense_setup)


def test_dense_rejects_a_dimension_mismatch(dense_setup, monkeypatch):
    monkeypatch.setattr(_FakeEncoder, "DIM", 4)

    with pytest.raises(SystemExit, match="embedding dimension"):
        run_dense(dense_setup)


@pytest.mark.parametrize(("argument", "value", "message"), [
    ("dense_model", "other-model", "--dense-model"),
    ("dense_revision", "other-revision", "--dense-revision"),
    ("dense_pooling", "cls", "--dense-pooling"),
    ("dense_max_length", 64, "--dense-max-length"),
])
def test_dense_rejects_query_settings_that_conflict_with_the_cache(
        dense_setup, argument, value, message):
    with pytest.raises(SystemExit, match=message):
        run_dense(dense_setup, **{argument: value})


def test_dense_and_hybrid_can_be_reported_for_an_empty_applicable_set(
        dense_setup):
    dense_setup["rows"] = []

    results = run_dense(dense_setup)

    assert results["dense"]["primary"]["applicable_rows"] == 0
    assert results["dense"]["primary"]["recall_rows"] == {
        "1": 0.0, "5": 0.0, "10": 0.0, "20": 0.0}
    assert results["hybrid"]["primary"]["applicable_rows"] == 0
