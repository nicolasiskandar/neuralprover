"""The evaluation: what a run counts, and what it refuses to count."""
import json
import math

import pytest

from neuralproof.evaluation.metrics import summarize
from neuralproof.evaluation.tactic_prediction import _wilson, evaluate_tactic_prediction


def install_predictors(monkeypatch, base, lora):
    """Replace the model stack with two stand-ins and record how they were asked for."""
    calls = []

    def fake_load(model_id, adapter=None, revision=None):
        calls.append({"model_id": model_id, "adapter": adapter, "revision": revision})
        return base if adapter is None else lora

    monkeypatch.setattr("neuralproof.models.predictor.load_hf_predictor", fake_load)
    return calls


class Silent:
    def predict(self, state, k):
        return []


class Fixed:
    def __init__(self, tactic):
        self.tactic = tactic

    def predict(self, state, k):
        from neuralproof.lean.client import TacticCandidate
        return [TacticCandidate(self.tactic)]


# --- the metrics -----------------------------------------------------------

def test_counts():
    assert summarize([{"verified": True}, {"verified": False}])["verified"] == 1


def test_unmeasured_tokens_are_not_zero():
    assert summarize([{"verified": False, "inference_tokens": None}])["inference_tokens"] is None


def test_an_empty_run_reports_nothing_rather_than_dividing_by_zero():
    summary = summarize([])
    assert summary["attempted"] == 0
    assert summary["verified"] == 0
    assert summary["solve_rate"] == 0.0
    assert summary["solve_rate_wilson95"] is None
    assert summary["mean_nodes_expanded"] is None
    assert summary["mean_tactic_calls"] is None
    assert summary["mean_solve_seconds"] is None
    assert summary["median_solve_seconds"] is None
    assert summary["inference_tokens"] is None


def test_invalid_tactics_and_timeouts_are_totalled():
    summary = summarize([{"verified": False, "invalid_tactics": 2, "timeouts": 1},
                         {"verified": False, "invalid_tactics": 3, "timeouts": 0}])
    assert summary["invalid_tactics"] == 5
    assert summary["timeouts"] == 1


def test_the_solve_time_is_taken_over_the_verified_rows_only():
    summary = summarize([{"verified": True, "solve_seconds": 10.0},
                         {"verified": False, "solve_seconds": 100.0}])
    assert summary["mean_solve_seconds"] == 10.0
    assert summary["median_solve_seconds"] == 10.0


def test_the_node_and_call_counts_are_averaged_over_the_attempts():
    summary = summarize([{"verified": True, "expanded": 2, "tactic_calls": 3},
                         {"verified": False, "expanded": 4, "tactic_calls": 5}])
    assert summary["mean_nodes_expanded"] == 3.0
    assert summary["mean_tactic_calls"] == 4.0


def test_pass_at_10_is_reported_as_unmeasured():
    # The benchmark records one search run per theorem, so a pass@10 number
    # would be a claim the data does not support.
    summary = summarize([{"verified": True}])
    assert summary["pass_at_10"] is None
    assert "not measured" in summary["pass_at_10_note"]


def test_pass_at_k_estimator_values():
    from neuralproof.evaluation.metrics import pass_at_k
    # If c == 0, pass@k is 0
    assert pass_at_k(10, 0, 1) == 0.0
    assert pass_at_k(10, 0, 10) == 0.0
    # If c == n, pass@k is 1.0
    assert pass_at_k(10, 10, 1) == 1.0
    assert pass_at_k(10, 10, 10) == 1.0
    # If n - c < k, at least one success in any sample of size k
    assert pass_at_k(10, 5, 6) == 1.0
    # Boundary / invalid
    assert pass_at_k(5, 2, 10) == 0.0
    assert pass_at_k(0, 0, 1) == 0.0


def test_pass_at_10_is_computed_when_repeat_attempts_exist():
    # 2 theorems, each attempted 10 times: one solved 2 times, one solved 0 times
    summary = summarize([
        {"verified": True, "attempts": 10, "verified_attempts": 2},
        {"verified": False, "attempts": 10, "verified_attempts": 0},
    ])
    assert summary["pass_at_10"] is not None
    # Theorem 1: n=10, c=2, k=10 -> 1 - binom(8,10)/binom(10,10) = 1 - 0 = 1.0
    # Theorem 2: n=10, c=0, k=10 -> 0.0
    # Mean: 0.5
    assert summary["pass_at_10"] == pytest.approx(0.5)



# --- the confidence interval ------------------------------------------------

def test_the_interval_is_absent_without_a_sample():
    assert _wilson(0, 0) is None


def test_the_interval_contains_the_observed_rate():
    for correct, total in ((0, 10), (1, 10), (5, 10), (9, 10), (10, 10)):
        low, high = _wilson(correct, total)
        assert low <= correct / total <= high


def test_an_all_failures_interval_starts_at_zero():
    low, high = _wilson(0, 50)
    assert low == 0.0
    assert 0.0 < high < 0.1


def test_an_all_successes_interval_ends_at_one():
    low, high = _wilson(50, 50)
    assert high == 1.0
    assert 0.9 < low < 1.0


def test_the_interval_matches_its_published_value():
    # A regression guard on the formula itself, not only on its shape.
    low, high = _wilson(1, 1)
    assert low == pytest.approx(0.2065433, abs=1e-6)
    assert high == 1.0


# --- the held-out tactic metric ---------------------------------------------

def test_tactic_prediction_uses_same_deterministic_single_line_test_sample(monkeypatch, tmp_path,
                                                                           tactic_row):
    rows = [tactic_row(example_id="a", split="test", target_tactic="trivial"),
            tactic_row(example_id="b", split="test", target_tactic="exact\nTrue.intro"),
            tactic_row(example_id="c", split="train", target_tactic="trivial")]
    source = tmp_path / "test.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows))
    install_predictors(monkeypatch, Fixed("trivial"), Fixed("rfl"))
    result = evaluate_tactic_prediction(source, tmp_path / "result.json", base_model="base",
                                        revision="rev", adapter="lora", limit=10)
    assert result["heldout_examples"] == 2
    assert result["eligible_single_line_examples"] == 1
    assert result["base"]["exact_matches"] == 1
    assert result["lora"]["attempted"] == 1
    assert result["base"]["wilson95"][0] == pytest.approx(0.2065433, abs=1e-6)
    assert result["base"]["wilson95"][1] == 1.0


def test_a_silent_model_is_reported_separately_from_a_wrong_tactic(monkeypatch, tmp_path, tactic_row):
    rows = [tactic_row(example_id="a", split="test", target_tactic="trivial")]
    source = tmp_path / "test.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows))
    install_predictors(monkeypatch, Silent(), Silent())
    result = evaluate_tactic_prediction(source, tmp_path / "result.json", base_model="base",
                                        revision="rev", adapter="lora", limit=10)
    assert result["base"]["exact_matches"] == 0
    assert result["base"]["silent_predictions"] == 1
    assert result["lora"]["silent_predictions"] == 1


def test_a_silent_model_is_not_counted_as_a_wrong_tactic(monkeypatch, tmp_path, tactic_row):
    # The two numbers answer different questions, and a report that mixes
    # them cannot tell a model that stayed quiet from one that guessed wrong.
    rows = [tactic_row(example_id="a", split="test", target_tactic="trivial")]
    source = tmp_path / "test.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows))
    install_predictors(monkeypatch, Silent(), Fixed("wrong"))
    result = evaluate_tactic_prediction(source, tmp_path / "result.json", base_model="base",
                                        revision="rev", adapter="lora", limit=10)
    assert result["base"]["exact_matches"] == 0
    assert result["base"]["silent_predictions"] == 1
    assert result["lora"]["exact_matches"] == 0
    assert result["lora"]["silent_predictions"] == 0


def test_non_tactic_targets_are_excluded_from_the_metric(monkeypatch, tmp_path, tactic_row):
    rows = [tactic_row(example_id="a", split="test", target_tactic="trivial"),
            tactic_row(example_id="b", split="test", target_tactic="by"),
            tactic_row(example_id="c", split="test", target_tactic="where")]
    source = tmp_path / "test.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows))
    install_predictors(monkeypatch, Fixed("trivial"), Fixed("rfl"))
    result = evaluate_tactic_prediction(source, tmp_path / "result.json", base_model="base",
                                        revision="rev", adapter="lora", limit=10)
    assert result["excluded_non_tactic_targets"] == 2
    assert result["eligible_single_line_examples"] == 1
    assert result["base"]["attempted"] == 1


def test_focus_local_rows_are_excluded_and_counted(monkeypatch, tmp_path, tactic_row):
    # A focus-local state is not a state the live client reports, so scoring
    # the model on it would measure something that never happens at
    # inference.  The exclusion stays visible in the result.
    rows = [tactic_row(example_id="a", split="test", target_tactic="trivial",
                       goal_state="⊢ p", result_state="no goals"),
            tactic_row(example_id="b", split="test", target_tactic="trivial",
                       goal_state="⊢ q", result_state="no goals")]
    source = tmp_path / "test.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows))
    install_predictors(monkeypatch, Fixed("trivial"), Fixed("trivial"))
    result = evaluate_tactic_prediction(source, tmp_path / "result.json", base_model="base",
                                        revision="rev", adapter="lora", limit=10)
    assert result["excluded_focus_scope"] == 1
    assert result["eligible_single_line_examples"] == 1
    assert result["base"]["attempted"] == 1


def test_the_exclusion_counters_account_for_every_held_out_row(monkeypatch, tmp_path, tactic_row):
    rows = [tactic_row(example_id="a", split="test", target_tactic="trivial",
                       source_declaration="d1", goal_state="⊢ p", result_state="no goals"),
            tactic_row(example_id="b", split="test", target_tactic="trivial",
                       source_declaration="d1", goal_state="⊢ q", result_state="no goals"),
            tactic_row(example_id="c", split="test", target_tactic="by",
                       source_declaration="d2"),
            tactic_row(example_id="d", split="test", target_tactic="trivial\nmore",
                       source_declaration="d3"),
            tactic_row(example_id="e", split="train", target_tactic="trivial",
                       source_declaration="d4")]
    source = tmp_path / "test.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows))
    install_predictors(monkeypatch, Fixed("trivial"), Fixed("trivial"))
    result = evaluate_tactic_prediction(source, tmp_path / "result.json", base_model="base",
                                        revision="rev", adapter="lora", limit=10)
    assert result["heldout_examples"] == 4
    assert result["excluded_non_tactic_targets"] == 1
    assert result["excluded_focus_scope"] == 1
    assert result["eligible_single_line_examples"] == 1


def test_a_multi_line_target_is_not_scored(monkeypatch, tmp_path, tactic_row):
    rows = [tactic_row(example_id="a", split="test", target_tactic="exact\nTrue.intro")]
    source = tmp_path / "test.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows))
    install_predictors(monkeypatch, Fixed("trivial"), Fixed("trivial"))
    with pytest.raises(ValueError, match="no held-out single-line tactic examples"):
        evaluate_tactic_prediction(source, tmp_path / "result.json", base_model="base",
                                   revision="rev", adapter="lora", limit=10)


def test_a_row_without_a_theorem_header_is_reported_clearly():
    # `evaluate` proves whole theorems; a mined row carries a goal state
    # and cannot be turned back into a theorem header.
    from neuralproof.evaluation.benchmark import theorem_header
    with pytest.raises(ValueError, match="evaluate-tactics"):
        theorem_header({"example_id": "x", "goal_state": "⊢ True", "target_tactic": "trivial"})


def test_a_row_with_a_theorem_header_is_used_as_the_statement():
    from neuralproof.evaluation.benchmark import theorem_header
    assert theorem_header({"theorem": "theorem t : True"}) == "theorem t : True"


def test_the_limit_has_to_be_positive(monkeypatch, tmp_path, tactic_row):
    source = tmp_path / "test.jsonl"
    source.write_text(json.dumps(tactic_row(split="test")) + "\n")
    install_predictors(monkeypatch, Fixed("trivial"), Fixed("trivial"))
    with pytest.raises(ValueError, match="limit must be positive"):
        evaluate_tactic_prediction(source, tmp_path / "result.json", base_model="base",
                                   revision="rev", adapter="lora", limit=0)


def test_the_sample_is_the_same_for_the_same_seed(monkeypatch, tmp_path, tactic_row):
    rows = [tactic_row(example_id=f"row-{index}", split="test",
                       source_file=f"Mathlib/{index}.lean") for index in range(20)]
    source = tmp_path / "test.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows))
    install_predictors(monkeypatch, Fixed("trivial"), Fixed("trivial"))
    first = evaluate_tactic_prediction(source, tmp_path / "one.json", base_model="base",
                                       revision="rev", adapter="lora", limit=5, seed="a-seed")
    second = evaluate_tactic_prediction(source, tmp_path / "two.json", base_model="base",
                                        revision="rev", adapter="lora", limit=5, seed="a-seed")
    assert [item["example_id"] for item in first["base"]["examples"]] == \
        [item["example_id"] for item in second["base"]["examples"]]


def test_the_sample_respects_the_limit(monkeypatch, tmp_path, tactic_row):
    rows = [tactic_row(example_id=f"row-{index}", split="test",
                       source_file=f"Mathlib/{index}.lean") for index in range(20)]
    source = tmp_path / "test.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows))
    install_predictors(monkeypatch, Fixed("trivial"), Fixed("trivial"))
    result = evaluate_tactic_prediction(source, tmp_path / "result.json", base_model="base",
                                        revision="rev", adapter="lora", limit=5)
    assert result["sample_size"] == 5
    assert result["base"]["attempted"] == 5


def test_every_example_records_whether_the_model_spoke(monkeypatch, tmp_path, tactic_row):
    rows = [tactic_row(example_id="a", split="test", target_tactic="trivial")]
    source = tmp_path / "test.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows))
    install_predictors(monkeypatch, Fixed("trivial"), Fixed("trivial"))
    result = evaluate_tactic_prediction(source, tmp_path / "result.json", base_model="base",
                                        revision="rev", adapter="lora", limit=10)
    example = result["base"]["examples"][0]
    assert example["produced_output"] is True
    assert example["prediction"] == "trivial"
    assert example["target"] == "trivial"
    assert example["exact_match"] is True


def test_the_two_models_are_asked_for_the_same_rows(monkeypatch, tmp_path, tactic_row):
    rows = [tactic_row(example_id=f"row-{index}", split="test",
                       source_file=f"Mathlib/{index}.lean") for index in range(6)]
    source = tmp_path / "test.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows))
    install_predictors(monkeypatch, Fixed("trivial"), Fixed("trivial"))
    result = evaluate_tactic_prediction(source, tmp_path / "result.json", base_model="base",
                                        revision="rev", adapter="lora", limit=3)
    assert [item["example_id"] for item in result["base"]["examples"]] == \
        [item["example_id"] for item in result["lora"]["examples"]]


def test_the_result_is_written_to_the_output_file(monkeypatch, tmp_path, tactic_row):
    rows = [tactic_row(example_id="a", split="test", target_tactic="trivial")]
    source = tmp_path / "test.jsonl"
    source.write_text("".join(json.dumps(x) + "\n" for x in rows))
    install_predictors(monkeypatch, Fixed("trivial"), Fixed("trivial"))
    output = tmp_path / "result.json"
    evaluate_tactic_prediction(source, output, base_model="base", revision="rev",
                               adapter="lora", limit=10)
    written = json.loads(output.read_text())
    assert written["base"]["exact_matches"] == 1
    assert written["protocol"]
