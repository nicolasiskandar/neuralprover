"""The benchmark runner: the counts a search run produces.

`run` is driven with a stand-in Lean client so the accounting can be checked
without the toolchain.  The counts it produces are what an experiment report
quotes, so they have to be right even when nothing is proved.
"""
import csv
import json

import pytest

from neuralproof.evaluation.benchmark import run, theorem_header
from neuralproof.evaluation.metrics import summarize
from neuralproof.lean.client import ExecutionResult, ProofState, VerificationResult


class FakeClient:
    """A Lean client that answers with a fixed script instead of a kernel."""

    def __init__(self, failing=(), completing=("exact True.intro",)):
        self.failing = set(failing)
        self.completing = set(completing)
        self.calls = []
        self.timeout = 30

    def initial_state(self, theorem, context="import Lean"):
        return ProofState(theorem, context, goals=("⊢ True",))

    def inspect(self, state):
        return ExecutionResult(True, state, False, "")

    def apply(self, state, tactic):
        self.calls.append(tactic)
        if tactic in self.failing:
            return ExecutionResult(False, None, False, "unknown identifier 'nope'")
        return ExecutionResult(True, state, True, "")

    def render_proof(self, state):
        return state.theorem + " := by\n  " + "\n  ".join(state.prefix)

    def verify(self, proof, context="import Lean"):
        return VerificationResult(True, "", "", 0.0, ())


class OneTacticPredictor:
    def __init__(self, tactic="exact True.intro"):
        self.tactic = tactic

    def predict(self, state, k):
        from neuralproof.lean.client import TacticCandidate
        return [TacticCandidate(self.tactic, 1.0)]


def test_a_verified_theorem_is_written_with_its_proof(tmp_path):
    output = tmp_path / "results.jsonl"
    rows = [{"theorem_id": "t1", "theorem": "theorem t1 : True", "context": "import Lean"}]
    results = run(rows, FakeClient(), OneTacticPredictor(), output, max_nodes=2, width=1)
    assert results[0]["verified"] is True
    assert results[0]["proof"]
    written = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
    assert written[0]["theorem_id"] == "t1"
    assert written[0]["verified"] is True


def test_the_summary_and_the_csv_are_written_next_to_the_results(tmp_path):
    output = tmp_path / "results.jsonl"
    rows = [{"theorem_id": "t1", "theorem": "theorem t1 : True", "context": "import Lean"}]
    run(rows, FakeClient(), OneTacticPredictor(), output, max_nodes=2, width=1)
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["attempted"] == 1
    assert summary["verified"] == 1
    with (tmp_path / "results.csv").open() as stream:
        table = list(csv.DictReader(stream))
    assert table[0]["theorem_id"] == "t1"


def test_a_failing_tactic_is_counted_as_an_invalid_tactic(tmp_path):
    output = tmp_path / "results.jsonl"
    rows = [{"theorem_id": "t1", "theorem": "theorem t1 : True", "context": "import Lean"}]
    client = FakeClient(failing=("exact True.intro",))
    results = run(rows, client, OneTacticPredictor(), output, max_nodes=2, width=1)
    assert results[0]["verified"] is False
    assert results[0]["invalid_tactics"] == 1
    assert results[0]["proof"] is None


def test_a_timed_out_tactic_is_counted_as_a_timeout(tmp_path):
    class TimingOutClient(FakeClient):
        def apply(self, state, tactic):
            self.calls.append(tactic)
            return ExecutionResult(False, None, False, "Lean execution timed out")

    output = tmp_path / "results.jsonl"
    rows = [{"theorem_id": "t1", "theorem": "theorem t1 : True", "context": "import Lean"}]
    results = run(rows, TimingOutClient(), OneTacticPredictor(), output, max_nodes=2, width=1)
    assert results[0]["timeouts"] == 1
    assert results[0]["verified"] is False


def test_a_row_without_a_theorem_header_stops_the_run(tmp_path):
    output = tmp_path / "results.jsonl"
    rows = [{"theorem_id": "t1", "goal_state": "⊢ True", "target_tactic": "trivial"}]
    with pytest.raises(ValueError, match="evaluate-tactics"):
        run(rows, FakeClient(), OneTacticPredictor(), output, max_nodes=2, width=1)
    assert not output.exists()


def test_the_summary_of_a_run_counts_what_it_actually_verified(tmp_path):
    class FailFirstClient(FakeClient):
        def apply(self, state, tactic):
            self.calls.append(tactic)
            if len(self.calls) == 1:
                return ExecutionResult(False, None, False, "unknown identifier 'nope'")
            return ExecutionResult(True, state, True, "")

    output = tmp_path / "results.jsonl"
    rows = [{"theorem_id": "t1", "theorem": "theorem t1 : True", "context": "import Lean"},
            {"theorem_id": "t2", "theorem": "theorem t2 : True", "context": "import Lean"}]
    results = run(rows, FailFirstClient(), OneTacticPredictor(), output, max_nodes=2, width=1)
    summary = summarize(results)
    assert summary["attempted"] == 2
    assert summary["verified"] == 1
    assert summary["invalid_tactics"] == 1


def test_the_search_trace_is_kept_with_the_result(tmp_path):
    output = tmp_path / "results.jsonl"
    rows = [{"theorem_id": "t1", "theorem": "theorem t1 : True", "context": "import Lean"}]
    results = run(rows, FakeClient(), OneTacticPredictor(), output, max_nodes=2, width=1)
    assert results[0]["search_trace"]
    assert results[0]["tactic_calls"] == 1
