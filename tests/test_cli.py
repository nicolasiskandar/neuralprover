"""The command line surface: argument parsing and the commands' exit behaviour."""
import json

import pytest

from neuralproof.cli import main, parse_tactics


def run_cli(monkeypatch, *args):
    """Run the CLI with the given arguments and capture what it printed."""
    import sys

    monkeypatch.setattr(sys, "argv", ["neuralproof", *args])
    return main()


# --- tactic list parsing ---------------------------------------------------

def test_json_tactic_list_preserves_embedded_commas():
    tactic = "rw [Nat.div_div_eq_div_mul, Nat.mul_comm]"
    assert parse_tactics('["' + tactic + '"]') == [tactic]


def test_legacy_tactic_list():
    assert parse_tactics("rfl,trivial") == ["rfl", "trivial"]


def test_a_json_tactic_list_must_hold_strings():
    with pytest.raises(ValueError, match="string array"):
        parse_tactics("[1, 2]")


def test_a_json_value_that_is_not_an_array_is_read_as_a_legacy_list():
    # Only an array is treated as JSON; anything else falls back to the
    # comma-separated form the command has always accepted.
    assert parse_tactics('{"tactic": "rfl"}') == ['{"tactic": "rfl"}']


def test_malformed_json_is_reported():
    import json as _json

    with pytest.raises(_json.JSONDecodeError):
        parse_tactics('["rfl"')


# --- evaluate --------------------------------------------------------------

def test_evaluate_on_a_row_without_a_theorem_header_exits_with_a_clear_error(monkeypatch, tmp_path):
    # `evaluate` searches for a proof of a whole theorem, so it needs the
    # statement.  A mined row carries a goal state instead; the error has to
    # say so and point at the command that does score such rows.
    data = tmp_path / "mined.jsonl"
    data.write_text(json.dumps({"example_id": "x", "goal_state": "⊢ True",
                                "target_tactic": "trivial"}) + "\n")
    with pytest.raises(SystemExit) as caught:
        run_cli(monkeypatch, "evaluate", "--data", str(data),
                "--output", str(tmp_path / "out.jsonl"))
    assert "evaluate-tactics" in str(caught.value)


# --- preprocess ------------------------------------------------------------

def test_preprocess_writes_a_manifest_with_the_label_policy(monkeypatch, tmp_path, tactic_row):
    source = tmp_path / "rows.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in [
        tactic_row(example_id="a", split="train", target_tactic="trivial"),
        tactic_row(example_id="b", split="train", target_tactic="by"),
    ]))
    output = tmp_path / "processed"
    run_cli(monkeypatch, "preprocess", "--input", str(source), "--output", str(output))
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["split_counts"]["train"] == 1
    assert manifest["excluded_non_tactic_targets"] == 1
    assert "not a tactic" in manifest["label_policy"]
    assert manifest["code_diff_sha256"]
    assert manifest["input"]["rows"] == 2


def test_preprocess_is_deterministic(monkeypatch, tmp_path, tactic_row):
    rows = [tactic_row(example_id="a", split="train"),
            tactic_row(example_id="b", split="test", source_file="Mathlib/B.lean")]
    source = tmp_path / "rows.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in rows))
    first, second = tmp_path / "one", tmp_path / "two"
    run_cli(monkeypatch, "preprocess", "--input", str(source), "--output", str(first))
    run_cli(monkeypatch, "preprocess", "--input", str(source), "--output", str(second))
    for name in ("train.jsonl", "test.jsonl"):
        assert (first / name).read_text() == (second / name).read_text()


def test_preprocess_keeps_unvalidated_rows_only_when_asked(monkeypatch, tmp_path, tactic_row):
    source = tmp_path / "rows.jsonl"
    source.write_text(json.dumps(tactic_row(split="train",
                                            validation="transition_replay_pending")) + "\n")
    strict, loose = tmp_path / "strict", tmp_path / "loose"
    run_cli(monkeypatch, "preprocess", "--input", str(source), "--output", str(strict))
    run_cli(monkeypatch, "preprocess", "--input", str(source), "--output", str(loose),
            "--include-unvalidated")
    assert not (strict / "train.jsonl").read_text()
    kept = json.loads((loose / "train.jsonl").read_text().strip())
    assert kept["validation_status"] == "unreplayed"


# --- train -----------------------------------------------------------------

def test_train_rejects_a_zero_step_budget(monkeypatch, tmp_path):
    data = tmp_path / "rows.jsonl"
    data.write_text(json.dumps({"context": "import Lean", "goal_state": "⊢ True",
                                "target_tactic": "trivial"}) + "\n")
    with pytest.raises(ValueError, match="first step"):
        run_cli(monkeypatch, "train", "--data", str(data), "--output", str(tmp_path / "out"),
                "--max-steps", "0")


# --- doctor ----------------------------------------------------------------

@pytest.mark.lean
def test_doctor_reports_the_pinned_lean_version(monkeypatch, capsys):
    run_cli(monkeypatch, "doctor")
    assert "Lean (version 4.35.0" in capsys.readouterr().out


# --- replay-corpus ---------------------------------------------------------

def test_replay_corpus_subcommand_invokes_replay_corpus(monkeypatch, tmp_path, capsys):
    called_with = {}

    def fake_replay(input_file, mathlib_root, output, **kwargs):
        called_with.update({"input": input_file, "root": mathlib_root, "output": output, **kwargs})
        return {"status": "ok", "completed_files": 1}

    monkeypatch.setattr("neuralproof.data.replay_corpus.replay_corpus", fake_replay)
    fake_input = tmp_path / "in.jsonl"
    fake_input.write_text("{}\n")
    out_dir = tmp_path / "replayed"
    run_cli(monkeypatch, "data", "replay-corpus", "--input", str(fake_input),
            "--output", str(out_dir), "--files", "5", "--timeout", "60", "--no-resume")

    assert called_with["input"].resolve() == fake_input.resolve()
    assert called_with["output"].resolve() == out_dir.resolve()
    assert called_with["files"] == 5
    assert called_with["timeout"] == 60
    assert called_with["resume"] is False
    assert '"completed_files": 1' in capsys.readouterr().out


def test_replay_corpus_requires_input_argument(monkeypatch):
    with pytest.raises(SystemExit):
        run_cli(monkeypatch, "data", "replay-corpus")

