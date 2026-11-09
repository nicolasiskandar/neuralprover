"""Goal-aware ordering of interactive tactic suggestions."""
from __future__ import annotations

from neuralproof.lean.client import ProofState, TacticCandidate
from neuralproof.models.predictor import StaticPredictor
from neuralproof.suggestions import (RankedPredictor, candidate_priority,
                                     goal_targets, local_hypotheses,
                                     rank_candidates)


def _state(goals, context="import Lean"):
    return ProofState("theorem demo : True", context, (), tuple(goals), "demo")


def _order(state, *tactics):
    candidates = [TacticCandidate(tactic) for tactic in tactics]
    return [candidate.tactic for candidate in rank_candidates(state, candidates)]


def test_goal_targets_and_hypotheses_come_from_the_rendered_state():
    state = _state(("a b : Nat\nhp : a = b\n⊢ a + b = b + a",))

    assert goal_targets(state) == ("a + b = b + a",)
    assert local_hypotheses(state) == {"a": "Nat", "b": "Nat", "hp": "a = b"}


def test_rfl_is_demoted_for_a_commutative_equality_over_nat():
    state = _state(("a b : Nat\n⊢ a + b = b + a",))

    order = _order(state, "rfl", "trivial", "assumption", "simp", "omega")

    assert order.index("omega") < order.index("rfl")
    assert order[0] == "omega"


def test_ac_rfl_is_promoted_for_an_abstract_commutative_monoid():
    state = _state(
        ("α : Type\ninst✝ : AddCommMonoid α\na b : α\n⊢ a + b = b + a",),
        context="import Mathlib")

    order = _order(state, "rfl", "trivial", "assumption", "simp", "omega",
                   "exact True.intro", "ac_rfl")

    assert order[0] == "ac_rfl"
    assert order.index("ac_rfl") < order.index("rfl")


def test_rfl_is_promoted_for_a_reflexive_equality():
    state = _state(("a : Nat\n⊢ a = a",))

    order = _order(state, "trivial", "omega", "rfl")

    assert order[0] == "rfl"


def test_trivial_is_promoted_for_true():
    state = _state(("⊢ True",))

    order = _order(state, "rfl", "omega", "trivial", "exact True.intro")

    assert order[0] == "trivial"
    assert order.index("exact True.intro") < order.index("rfl")


def test_a_matching_hypothesis_is_promoted():
    state = _state(("hp : p\n⊢ p",))

    order = _order(state, "rfl", "trivial", "assumption", "exact hp")

    assert order[0] in {"assumption", "exact hp"}
    assert order.index("assumption") < order.index("rfl")
    assert order.index("exact hp") < order.index("rfl")


def test_constructor_is_promoted_for_a_conjunction():
    state = _state(("p q : Prop\n⊢ p ∧ q",))

    order = _order(state, "rfl", "assumption", "constructor")

    assert order[0] == "constructor"


def test_left_and_right_are_promoted_for_a_disjunction():
    state = _state(("p q : Prop\n⊢ p ∨ q",))

    order = _order(state, "rfl", "left", "right")

    assert set(order[:2]) == {"left", "right"}


def test_an_exact_commutativity_lemma_is_promoted():
    state = _state(("a b : Nat\n⊢ a + b = b + a",))

    order = _order(state, "rfl", "exact Nat.add_comm a b", "omega")

    assert order[0] == "exact Nat.add_comm a b"
    assert order.index("exact Nat.add_comm a b") < order.index("rfl")


def test_candidate_set_and_tie_order_are_preserved():
    state = _state(("p : Prop\n⊢ p",))

    order = _order(state, "first", "second", "third")

    assert order == ["first", "second", "third"]


def test_priority_is_not_a_probability_but_a_monotone_heuristic():
    state = _state(("a b : Nat\n⊢ a + b = b + a",))
    targets = goal_targets(state)
    hypotheses = local_hypotheses(state)

    assert (candidate_priority("omega", targets, hypotheses, state.context)
            > candidate_priority("rfl", targets, hypotheses, state.context))


def test_ranked_predictor_returns_the_top_k_in_goal_order():
    state = _state(("a b : Nat\n⊢ a + b = b + a",))
    predictor = RankedPredictor(
        StaticPredictor(["rfl", "trivial", "assumption", "simp", "omega"]))

    candidates = predictor.predict(state, 2)

    assert [candidate.tactic for candidate in candidates] == ["omega", "simp"]
    assert candidates[0].score > candidates[1].score


def test_ranked_predictor_can_pass_through_the_original_order():
    state = _state(("a b : Nat\n⊢ a + b = b + a",))
    predictor = RankedPredictor(
        StaticPredictor(["rfl", "omega"]), rank=False)

    candidates = predictor.predict(state, 2)

    assert [candidate.tactic for candidate in candidates] == ["rfl", "omega"]


def test_ranked_predictor_respects_a_zero_window():
    state = _state(("⊢ True",))
    predictor = RankedPredictor(StaticPredictor(["trivial"]))

    assert predictor.predict(state, 0) == []
