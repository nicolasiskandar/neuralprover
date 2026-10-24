"""The search: what is spent, what is refused, and what is reported."""
import pytest

from neuralproof.lean.client import LeanClient, TacticCandidate
from neuralproof.models.predictor import StaticPredictor
from neuralproof.search.best_first import best_first


@pytest.fixture(scope="module")
def client():
    return LeanClient(timeout=15)


def test_toy_search_verified(client):
    result = best_first(client, "theorem searched : True",
                        StaticPredictor(["exact True.intro"]), max_nodes=2, width=1)
    assert result.verified
    assert result.tactic_calls == 1


def test_node_budget(client):
    result = best_first(client, "theorem stuck : False", StaticPredictor(["trivial"]),
                        max_nodes=1, width=1)
    assert not result.verified
    assert result.expanded <= 1


def test_predictor_receives_inspected_initial_goal(client):
    class CapturingPredictor:
        goals = ()

        def predict(self, state, k):
            self.goals = state.goals
            return [TacticCandidate("exact True.intro", 1.0)]

    predictor = CapturingPredictor()
    result = best_first(client, "theorem goal_is_supplied : True", predictor,
                        max_nodes=1, width=1)
    assert result.verified
    assert predictor.goals == ("⊢ True",)


def test_an_empty_candidate_is_not_sent_to_lean(client):
    # An empty tactic is not a tactic; spending a Lean call on it wastes
    # the budget and reports a failure that the model never produced.
    class EmptyThenRealPredictor:
        def predict(self, state, k):
            return [TacticCandidate("", 1.0), TacticCandidate("exact True.intro", 0.5)]

    result = best_first(client, "theorem empty_candidate : True", EmptyThenRealPredictor(),
                        max_nodes=1, width=2)
    assert result.verified
    assert result.rejected_candidates == 1
    assert result.tactic_calls == 1


def test_a_predictor_that_only_returns_empty_candidates_makes_no_lean_call(client):
    class OnlyEmptyPredictor:
        def predict(self, state, k):
            return [TacticCandidate("") for _ in range(k)]

    result = best_first(client, "theorem all_empty : True", OnlyEmptyPredictor(),
                        max_nodes=2, width=2)
    assert not result.verified
    assert result.tactic_calls == 0
    assert result.rejected_candidates == 2


def test_a_rejected_candidate_is_visible_in_the_trace(client):
    # The budget that was spent on a refusal has to show up in the trace,
    # otherwise the run looks like it simply did not try.
    class OnlyEmptyPredictor:
        def predict(self, state, k):
            return [TacticCandidate("") for _ in range(k)]

    result = best_first(client, "theorem refused : True", OnlyEmptyPredictor(),
                        max_nodes=1, width=1)
    assert any(entry.get("rejected") == "empty candidate" for entry in result.trace)


def test_a_whitespace_only_candidate_is_refused(client):
    class WhitespacePredictor:
        def predict(self, state, k):
            return [TacticCandidate("   ")]

    result = best_first(client, "theorem blank : True", WhitespacePredictor(),
                        max_nodes=1, width=1)
    assert result.tactic_calls == 0
    assert result.rejected_candidates == 1


def test_a_failing_tactic_is_traced_with_its_error(client):
    class FailingPredictor:
        def predict(self, state, k):
            return [TacticCandidate("not_a_tactic", 1.0)]

    result = best_first(client, "theorem failing : True", FailingPredictor(),
                        max_nodes=1, width=1)
    assert not result.verified
    failures = [entry for entry in result.trace if entry.get("success") is False]
    assert failures
    assert failures[0]["tactic"] == "not_a_tactic"
    assert failures[0]["error"]


def test_an_unverifiable_completion_is_not_accepted(client):
    # A tactic that closes the goal but whose proof does not verify is not
    # a solution, and the search has to say so.
    class UnsoundPredictor:
        def predict(self, state, k):
            return [TacticCandidate("exact Nat.sorry", 1.0)]

    result = best_first(client, "theorem unsound : True", UnsoundPredictor(),
                        max_nodes=1, width=1)
    assert not result.verified
    assert result.proof is None


def test_the_trace_records_the_inspected_initial_state(client):
    result = best_first(client, "theorem traced : True", StaticPredictor(["exact True.intro"]),
                        max_nodes=1, width=1)
    assert result.trace[0]["initial_state_inspection"] is True
    assert result.trace[0]["goal_state"] == "⊢ True"


def test_a_failed_initial_inspection_is_reported(client):
    result = best_first(client, "theorem ill_typed : Nat := by exact True.intro",
                        StaticPredictor(["trivial"]), max_nodes=1, width=1)
    assert not result.verified
    assert result.tactic_calls == 0
    assert result.trace[0]["initial_state_inspection"] is False
    assert result.trace[0]["error"]
