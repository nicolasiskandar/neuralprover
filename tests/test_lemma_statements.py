"""The lemma-statement corpus builder: parsing, filtering, and provenance.

The Lean dumper is not run here.  These cases feed captured JSONL through the
Python half, so a malformed dump is rejected before it becomes a corpus, and
the deterministic writer keeps the artifact reproducible.
"""
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_builder():
    path = REPO_ROOT / "scripts" / "build_lemma_statements.py"
    spec = importlib.util.spec_from_file_location("build_lemma_statements", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = _load_builder()


def _dump(*records):
    return "".join(json.dumps(record) + "\n" for record in records)


def test_read_statement_dump_parses_blank_lines_and_deduplicates():
    text = (
        "\n"
        + _dump({"name": "Foo.bar", "kind": "theorem", "type": "x = y"})
        + _dump({"name": "Foo.bar", "kind": "theorem", "type": "x = y"})
        + _dump({"name": "Foo.baz", "kind": "theorem", "type": "y = z"})
        + "\n"
    )
    records = builder.read_statement_dump(text)
    assert [record["name"] for record in records] == ["Foo.bar", "Foo.baz"]


def test_read_statement_dump_rejects_a_conflicting_duplicate():
    text = _dump(
        {"name": "Foo.bar", "kind": "theorem", "type": "x = y"},
        {"name": "Foo.bar", "kind": "theorem", "type": "different"},
    )
    with pytest.raises(ValueError, match="conflicting duplicate"):
        builder.read_statement_dump(text)


@pytest.mark.parametrize("line", ["not json", "[]", '{"kind": "theorem"}'])
def test_read_statement_dump_rejects_malformed_lines(line):
    with pytest.raises(ValueError):
        builder.read_statement_dump(line + "\n")


def test_read_module_map_text_requires_a_tab_separator():
    modules = builder.read_module_map_text("A.B\tFoo.bar\n\nA.C\tFoo.baz\n")
    assert modules == {"Foo.bar": "A.B", "Foo.baz": "A.C"}
    with pytest.raises(ValueError, match="tab separator"):
        builder.read_module_map_text("A.B Foo.bar\n")


def test_internal_names_are_the_compiler_artifacts():
    for name in (
        "_private.Init.Prelude.0.foo",
        "Nat.foo._proof_1",
        "Nat.foo.match_1",
        "Nat.foo.noConfusion",
        "Nat.foo.recOn",
        "Nat.foo.casesOn",
        "Nat.foo.brecOn_1",
        "Nat.foo.below",
        "Nat.foo._flat_ctor",
        "Nat.foo.ctorIdx",
    ):
        assert builder.is_internal_name(name), name
    for name in ("Nat.add_comm", "Prod.isUnit_iff", "Foo.eq_1"):
        assert not builder.is_internal_name(name), name


def test_prepare_statements_filters_kinds_and_internal_names():
    records = [
        {"name": "Zeta.last", "kind": "theorem", "type": "z"},
        {"name": "Alpha.first", "kind": "theorem", "type": "a"},
        {"name": "Alpha.def", "kind": "def", "type": "d"},
        {"name": "Beta._proof_1", "kind": "theorem", "type": "p"},
    ]
    prepared, summary = builder.prepare_statements(
        records, kinds={"theorem"}, drop_internal=True)

    assert [record["name"] for record in prepared] == ["Alpha.first", "Zeta.last"]
    assert summary["input_kinds"] == {"def": 1, "theorem": 3}
    assert summary["input_count"] == 4
    assert summary["output_count"] == 2
    assert summary["dropped"] == {"internal": 1, "kind": 1}


def test_prepare_statements_joins_modules_and_counts_missing_ones():
    records = [
        {"name": "Foo.bar", "kind": "theorem", "type": "x = y"},
        {"name": "Foo.baz", "kind": "theorem", "type": "y = z"},
    ]
    prepared, summary = builder.prepare_statements(
        records, {"Foo.bar": "Mathlib.Foo"}, drop_internal=False)

    assert prepared[0]["module"] == "Mathlib.Foo"
    assert "module" not in prepared[1]
    assert summary["missing_modules"] == 1


def test_prepare_statements_can_drop_equation_lemmas():
    records = [
        {"name": "Foo.eq_1", "kind": "theorem", "type": "x = y"},
        {"name": "Foo.eq_2", "kind": "theorem", "type": "x = y"},
        {"name": "Foo.named", "kind": "theorem", "type": "x = y"},
    ]
    _, summary = builder.prepare_statements(
        records, drop_internal=False, drop_equation_lemmas=True)
    assert summary["dropped"] == {"equation_lemma": 2}
    assert summary["output_count"] == 1


def test_write_corpus_is_deterministic_and_gzip_readable(tmp_path):
    records = [
        {"name": "Foo.bar", "kind": "theorem", "type": "x = y", "module": "M"},
        {"name": "Foo.baz", "kind": "theorem", "type": "y = z"},
    ]
    first = tmp_path / "first.jsonl.gz"
    second = tmp_path / "second.jsonl.gz"
    builder.write_corpus(first, records)
    builder.write_corpus(second, records)

    assert first.read_bytes() == second.read_bytes()
    with gzip.open(first, "rt", encoding="utf-8") as stream:
        lines = [json.loads(line) for line in stream if line.strip()]
    assert lines == records
    # ``module`` is omitted rather than written as null when it is unknown.
    assert list(lines[0]) == ["name", "kind", "type", "module"]
    assert list(lines[1]) == ["name", "kind", "type"]
