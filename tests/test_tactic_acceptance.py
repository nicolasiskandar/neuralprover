"""Held-out acceptance selection, status classification, and aggregation."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from neuralproof.evaluation import tactic_acceptance as acceptance
from neuralproof.lean.transition import HarnessRun


def _item(example_id, *, source_file="Mathlib/A.lean", target="simp",
          syntax_kind="Lean.Parser.Tactic.simp", prediction="simp",
          exact=False):
    return {
        "example_id": example_id,
        "row": {
            "example_id": example_id,
            "source_file": source_file,
            "source_declaration": "A.decl",
            "source_line": 1,
            "target_tactic": target,
            "syntax_kind": syntax_kind,
        },
        "predictions": {"base": prediction, "lora": prediction},
        "exact_match": {"base": exact, "lora": exact},
        "produced_output": {"base": bool(prediction),
                            "lora": bool(prediction)},
    }


def test_select_rows_keeps_the_eval_order_and_joins_corpus_rows(tmp_path):
    examples = tmp_path / "examples.jsonl"
    examples.write_text("".join(json.dumps(row) + "\n" for row in [
        {"example_id": "b", "source_file": "Mathlib/B.lean",
         "source_declaration": "B.decl", "target_tactic": "rfl",
         "syntax_kind": "Lean.Parser.Tactic.tacticRfl"},
        {"example_id": "a", "source_file": "Mathlib/A.lean",
         "source_declaration": "A.decl", "target_tactic": "simp",
         "syntax_kind": "Lean.Parser.Tactic.simp"},
    ]))
    eval_path = tmp_path / "eval.json"
    eval_path.write_text(json.dumps({
        "base": {"examples": [
            {"example_id": "a", "prediction": "simp", "exact_match": True},
            {"example_id": "b", "prediction": "rfl", "exact_match": False},
        ]},
        "lora": {"examples": [
            {"example_id": "a", "prediction": "simp", "exact_match": True},
            {"example_id": "b", "prediction": "exact rfl", "exact_match": False},
        ]},
    }))
    rows = acceptance.select_rows(examples, eval_path, ["base", "lora"])
    assert [row["example_id"] for row in rows] == ["a", "b"]
    assert rows[0]["row"]["source_declaration"] == "A.decl"
    assert rows[1]["predictions"]["lora"] == "exact rfl"
    assert rows[0]["exact_match"]["base"] is True


def test_select_rows_rejects_different_model_id_sets(tmp_path):
    examples = tmp_path / "examples.jsonl"
    examples.write_text(json.dumps({
        "example_id": "a", "target_tactic": "simp"}) + "\n")
    eval_path = tmp_path / "eval.json"
    eval_path.write_text(json.dumps({
        "base": {"examples": [{"example_id": "a", "prediction": "simp"}]},
        "lora": {"examples": [{"example_id": "b", "prediction": "simp"}]},
    }))
    try:
        acceptance.select_rows(examples, eval_path, ["base", "lora"])
    except ValueError as error:
        assert "same example ids" in str(error)
    else:
        raise AssertionError("mismatched eval sections were accepted")


def test_sample_rows_is_deterministic_and_stratifies_by_family():
    rows = [
        _item("1", target="simp"),
        _item("2", target="simp"),
        _item("3", target="rw"),
        _item("4", target="exact"),
        _item("5", target="simp"),
    ]
    selected = acceptance.sample_rows(rows, 3, "family")
    assert [row["example_id"] for row in selected] == ["4", "3", "1"]


def test_sample_rows_by_file_round_robins_files():
    rows = [
        _item("1", source_file="Mathlib/A.lean"),
        _item("2", source_file="Mathlib/A.lean"),
        _item("3", source_file="Mathlib/B.lean"),
    ]
    selected = acceptance.sample_rows(rows, 2, "file")
    assert [row["example_id"] for row in selected] == ["1", "3"]


def _record(example_id, statuses, *, exact=False, family="simp",
            source_file="Mathlib/A.lean", target_kind="tactic",
            self_status="closed"):
    return {
        "example_id": example_id,
        "family": family,
        "source_file": source_file,
        "transition": {"target_kind": target_kind, "is_fragment": False},
        "self_check": {"status": self_status, "reason": None,
                       "elapsed_seconds": 0.0},
        "models": {
            model: {"status": status, "exact_match": exact,
                    "elapsed_seconds": 1.0}
            for model, status in statuses.items()
        },
    }


def test_aggregate_counts_and_rates():
    records = [
        _record("1", {"base": "closed", "lora": "accepted"}, exact=True),
        _record("2", {"base": "rejected", "lora": "rejected"}),
        _record("3", {"base": "empty", "lora": "closed"}),
        _record("4", {"base": "timeout", "lora": "unsupported"},
                self_status="rejected"),
    ]
    result = acceptance.aggregate(records, ["base", "lora"])
    base = result["models"]["base"]
    assert base["status_counts"] == {
        "closed": 1, "accepted": 0, "rejected": 1, "empty": 1,
        "timeout": 1, "unsupported": 0}
    assert base["supported_rows"] == 4
    assert base["evaluable_rows"] == 3
    assert base["accepted_or_closed"] == 1
    assert base["acceptance_rate_supported"] == 0.25
    assert base["acceptance_rate_evaluated"] == 1 / 3
    assert base["exact_matches"] == 1
    assert result["self_check"] == {"closed": 3, "rejected": 1}
    assert result["paired"]["lora_only"] == 1
    assert result["paired"]["both_accepted_or_closed"] == 1
    assert result["by_target_kind"]["tactic"]["base"]["rows"] == 4


def test_process_row_distinguishes_closed_accepted_empty_and_placeholder(
        tmp_path, monkeypatch):
    source = tmp_path / "A.lean"
    source.write_text("import Lean\n")

    def fake_build(trace, source_file, row, replacement=None, *,
                   project_dir=None, close_remaining=False):
        text = b"self" if replacement is None else replacement.encode("utf-8")
        return SimpleNamespace(
            text=text,
            span=SimpleNamespace(as_dict=lambda: {
                "target_kind": "tactic", "is_fragment": False}),
        )

    def fake_run(text, *, project_dir=None, timeout=120):
        text = text.decode("utf-8")
        if text.startswith("self"):
            return HarnessRun(0, (), "", "", False, 0.1)
        if text == "closed":
            return HarnessRun(0, (), "", "", False, 0.1)
        if text == "accepted":
            return HarnessRun(
                1, ({"severity": "error", "data": "unsolved goals"},),
                "", "", False, 0.1)
        return HarnessRun(
            1, ({"severity": "error", "data": "unknown tactic"},),
            "", "", False, 0.1)

    monkeypatch.setattr(acceptance, "build_harness", fake_build)
    monkeypatch.setattr(acceptance, "run_harness", fake_run)

    item = _item("1", prediction="closed")
    item["predictions"] = {"base": "closed", "lora": "accepted"}
    record = acceptance.process_row(
        item, {}, source, models=["base", "lora"], timeout=1)
    assert record["self_check"]["status"] == "closed"
    assert record["models"]["base"]["status"] == "closed"
    assert record["models"]["lora"]["status"] == "accepted"

    item = _item("2", prediction="")
    item["predictions"] = {"base": "", "lora": "sorry"}
    record = acceptance.process_row(
        item, {}, source, models=["base", "lora"], timeout=1)
    assert record["models"]["base"]["status"] == "empty"
    assert record["models"]["lora"]["status"] == "rejected"
    assert record["models"]["lora"]["reason"] == "placeholder_token"


def test_process_row_marks_a_failed_self_check_unsupported(tmp_path, monkeypatch):
    source = tmp_path / "A.lean"
    source.write_text("import Lean\n")

    def fake_build(trace, source_file, row, replacement=None, *,
                   project_dir=None, close_remaining=False):
        return SimpleNamespace(
            text=b"self",
            span=SimpleNamespace(as_dict=lambda: {
                "target_kind": "tactic", "is_fragment": False}),
        )

    def fake_run(text, *, project_dir=None, timeout=120):
        return HarnessRun(
            1, ({"severity": "error", "data": "unknown tactic"},),
            "", "", False, 0.1)

    monkeypatch.setattr(acceptance, "build_harness", fake_build)
    monkeypatch.setattr(acceptance, "run_harness", fake_run)

    item = _item("1", prediction="closed")
    record = acceptance.process_row(
        item, {}, source, models=["base", "lora"], timeout=1)
    assert record["self_check"]["status"] == "rejected"
    assert record["models"]["base"]["status"] == "unsupported"
    assert record["models"]["lora"]["status"] == "unsupported"


def test_process_row_falls_back_to_an_accepted_self_check(tmp_path, monkeypatch):
    source = tmp_path / "A.lean"
    source.write_text("import Lean\n")

    def fake_build(trace, source_file, row, replacement=None, *,
                   project_dir=None, close_remaining=False):
        if replacement is None:
            text = b"close" if close_remaining else b"noclose"
        else:
            text = replacement.encode("utf-8")
        return SimpleNamespace(
            text=text,
            span=SimpleNamespace(as_dict=lambda: {
                "target_kind": "tactic", "is_fragment": False}),
        )

    def fake_run(text, *, project_dir=None, timeout=120):
        if text == b"close":
            return HarnessRun(
                1, ({"severity": "error", "data": "unexpected identifier"},),
                "", "", False, 0.1)
        if text == b"noclose":
            return HarnessRun(
                1, ({"severity": "error", "data": "unsolved goals"},),
                "", "", False, 0.1)
        return HarnessRun(0, (), "", "", False, 0.1)

    monkeypatch.setattr(acceptance, "build_harness", fake_build)
    monkeypatch.setattr(acceptance, "run_harness", fake_run)

    item = _item("1", prediction="trivial")
    record = acceptance.process_row(
        item, {}, source, models=["base", "lora"], timeout=1)
    assert record["self_check"]["status"] == "accepted"
    assert record["self_check"]["strategy"] == "no_close"
    assert record["models"]["base"]["status"] == "closed"
    assert record["models"]["lora"]["status"] == "closed"


def test_a_self_check_closed_with_sorry_is_accepted_not_closed(tmp_path, monkeypatch):
    # `all_goals sorry` finishing elaboration is not a proof: Lean warns that
    # the declaration uses `sorry`, so the row is accepted evidence only.
    source = tmp_path / "A.lean"
    source.write_text("import Lean\n")

    def fake_build(trace, source_file, row, replacement=None, *,
                   project_dir=None, close_remaining=False):
        text = b"self-check" if replacement is None else replacement.encode("utf-8")
        return SimpleNamespace(
            text=text,
            span=SimpleNamespace(as_dict=lambda: {
                "target_kind": "tactic", "is_fragment": False}),
        )

    def fake_run(text, *, project_dir=None, timeout=120):
        if text == b"self-check":
            return HarnessRun(
                0, ({"severity": "warning", "data": "declaration uses `sorry`"},),
                "", "", False, 0.1)
        return HarnessRun(0, (), "", "", False, 0.1)

    monkeypatch.setattr(acceptance, "build_harness", fake_build)
    monkeypatch.setattr(acceptance, "run_harness", fake_run)

    item = _item("1", prediction="trivial")
    record = acceptance.process_row(
        item, {}, source, models=["base", "lora"], timeout=1)
    assert record["self_check"]["status"] == "accepted"
    assert record["self_check"]["reason"] == "remaining_goals_closed_by_harness"
    assert record["self_check"]["strategy"] == "close_remaining"
    assert record["models"]["base"]["status"] == "closed"
    assert record["models"]["lora"]["status"] == "closed"


def test_markdown_report_includes_status_tables():
    records = [
        _record("1", {"base": "closed", "lora": "accepted"}, exact=True),
        _record("2", {"base": "rejected", "lora": "rejected"}),
    ]
    payload = {
        "protocol": {"timeout_seconds": 1, "workers": 1,
                     "trace_cache": "cache", "source_revision": "rev",
                     "lean_toolchain": "toolchain"},
        "rows": len(records),
        **acceptance.aggregate(records, ["base", "lora"]),
    }
    text = acceptance.markdown_report(payload)
    assert "# Kernel-checked tactic acceptance" in text
    assert "| `base` |" in text
    assert "Both accepted or closed: 1" in text


def test_write_report_writes_json_and_markdown(tmp_path):
    payload = {"rows": 0, "models": {}, "by_target_kind": {},
               "protocol": {}}
    from neuralproof.evaluation.tactic_acceptance import markdown_report
    report_json, report_md = acceptance.write_report(tmp_path, payload)
    assert report_json.is_file()
    assert report_md.is_file()
    assert json.loads(report_json.read_text())["rows"] == 0
    assert report_md.read_text().startswith(
        "# Kernel-checked tactic acceptance")
