"""Lexical retrieval: tokenizer, BM25 ranking, exclusion, and corpus reading.

These tests use tiny in-memory corpora.  They check that retrieval is
deterministic and that the pieces compose; they say nothing about whether a
retrieved lemma can be applied, which only Lean can decide.
"""
import gzip
import json

import pytest

from neuralproof.retrieval import (
    BM25Index,
    Statement,
    build_index,
    iter_statements,
    read_statement_corpus,
    tokenize,
)


def test_tokenizer_splits_dots_underscores_and_camel_case():
    assert tokenize("Finset.sum_comm") == ["finset", "sum", "comm"]
    assert tokenize("Prod.isUnit_iff") == ["prod", "is", "unit"]
    assert tokenize("isUnitMul") == ["is", "unit", "mul"]


def test_tokenizer_drops_lean_syntax_and_stopwords():
    assert tokenize("theorem Foo.add : (a) [b]") == ["foo", "add", "a", "b"]
    assert tokenize("by fun x") == ["x"]


def test_tokenizer_keeps_unicode_letters_and_does_not_crash_on_none():
    assert tokenize("IsUnit (α : ℕ)") == ["is", "unit", "α", "ℕ"]
    assert tokenize("") == []


def test_statement_document_includes_the_type_only_when_asked():
    statement = Statement(name="Foo.bar", kind="theorem", type="x = y")
    assert statement.document(include_type=False) == "Foo.bar"
    assert statement.document(include_type=True) == "Foo.bar x = y"


def test_bm25_ranks_the_document_that_matches_the_query():
    index = BM25Index()
    index.add("Alpha.sum_comm", "sum over comm")
    index.add("Beta.prod_assoc", "product assoc")
    index.add("Gamma.add_zero", "adding zero")
    index.finalize()

    results = index.search("sum comm", k=3)
    assert results[0][0] == "Alpha.sum_comm"
    assert results[0][1] > 0


def test_bm25_is_deterministic_and_breaks_ties_by_name():
    index = BM25Index()
    index.add("Alpha.lemma", "same text")
    index.add("Beta.lemma", "same text")
    index.finalize()

    first = index.search("same", k=2, max_df_ratio=1.0)
    second = index.search("same", k=2, max_df_ratio=1.0)
    assert first == second
    assert [name for name, _ in first] == ["Alpha.lemma", "Beta.lemma"]


def test_bm25_excludes_requested_names():
    index = BM25Index()
    index.add("Alpha.sum", "sum")
    index.add("Beta.sum", "sum")
    index.finalize()

    assert index.search("sum", k=1, max_df_ratio=1.0)[0][0] == "Alpha.sum"
    assert index.search("sum", k=1, max_df_ratio=1.0,
                        exclude={"Alpha.sum"})[0][0] == "Beta.sum"
    assert index.search("sum", k=1, max_df_ratio=1.0,
                        exclude={"Alpha.sum", "Beta.sum"}) == []


def test_bm25_returns_nothing_for_an_empty_query_or_zero_k():
    index = BM25Index()
    index.add("Alpha.sum", "sum")
    index.finalize()
    assert index.search("", k=5) == []
    assert index.search("sum", k=0) == []


def test_bm25_drops_query_terms_that_occur_in_most_documents():
    index = BM25Index()
    index.add("Alpha.common", "common rare_one")
    index.add("Beta.common", "common")
    index.add("Gamma.common", "common")
    index.finalize()

    # ``common`` is in every document and is removed by the max-df filter;
    # ``rare_one`` still identifies the first document.
    assert index.search("common rare_one", k=3)[0][0] == "Alpha.common"


def test_build_index_can_index_names_without_types():
    statements = [
        Statement(name="Finset.sum_comm", kind="theorem", type="unrelated words"),
        Statement(name="Nat.add_comm", kind="theorem", type="padding words"),
    ]
    name_only = build_index(statements, include_type=False)
    with_type = build_index(statements, include_type=True)

    assert name_only.search("sum", k=1)[0][0] == "Finset.sum_comm"
    assert name_only.search("padding", k=1) == []
    assert with_type.search("padding", k=1)[0][0] == "Nat.add_comm"


def _write_corpus(path, rows, *, gz):
    payload = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
    if gz:
        path.write_bytes(gzip.compress(payload, mtime=0))
    else:
        path.write_bytes(payload)


def test_read_statement_corpus_reads_gzip_and_plain(tmp_path):
    rows = [
        {"name": "Foo.bar", "kind": "theorem", "type": "x = y", "module": "M"},
        {"name": "Foo.baz", "kind": "theorem", "type": "y = z"},
    ]
    gz_path = tmp_path / "corpus.jsonl.gz"
    plain_path = tmp_path / "corpus.jsonl"
    _write_corpus(gz_path, rows, gz=True)
    _write_corpus(plain_path, rows, gz=False)

    for path in (gz_path, plain_path):
        statements = read_statement_corpus(path)
        assert [s.name for s in statements] == ["Foo.bar", "Foo.baz"]
        assert statements[0].module == "M"
        assert statements[1].module is None


def test_read_statement_corpus_reports_a_missing_field(tmp_path):
    path = tmp_path / "corpus.jsonl"
    _write_corpus(path, [{"name": "Foo.bar", "kind": "theorem"}], gz=False)
    with pytest.raises(ValueError, match=r"corpus\.jsonl:1 missing type"):
        read_statement_corpus(path)


def test_iter_statements_streams_rows(tmp_path):
    path = tmp_path / "corpus.jsonl"
    _write_corpus(path, [
        {"name": "Foo.bar", "kind": "theorem", "type": "x = y"},
        {"name": "Foo.baz", "kind": "theorem", "type": "y = z"},
    ], gz=False)

    assert [s.name for s in iter_statements(path)] == ["Foo.bar", "Foo.baz"]
