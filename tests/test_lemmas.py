"""The lemma pre-filter: what it extracts, what it refuses, and what it must not."""
import json

import pytest

from neuralproof.lean.client import ExecutionResult, ProofState, TacticCandidate, VerificationResult
from neuralproof.lemmas import (
    extract_symbol_heads,
    filter_tactic,
    is_known_symbol,
    load_lemma_index,
    symbols_in_state,
)
from neuralproof.search.best_first import best_first


class FakeClient:
    """A stand-in Lean client so filter accounting is testable without Lean."""

    def __init__(self):
        self.calls = []
        self.timeout = 30

    def initial_state(self, theorem, context="import Lean"):
        return ProofState(theorem, context, goals=("⊢ True",))

    def inspect(self, state):
        return ExecutionResult(True, state, False, "")

    def apply(self, state, tactic):
        self.calls.append(tactic)
        return ExecutionResult(True, state, True, "")

    def render_proof(self, state):
        return state.theorem + " := by\n  " + "\n  ".join(state.prefix)

    def verify(self, proof, context="import Lean"):
        return VerificationResult(True, "", "", 0.0, ())


def _predictor(tactic):
    class _Predictor:
        def predict(self, state, k):
            return [TacticCandidate(tactic, 1.0)]

    return _Predictor()


def _write_index(tmp_path, names):
    path = tmp_path / "lemma_index.json"
    path.write_text(json.dumps(sorted(names)))
    return path


# --- extraction -----------------------------------------------------------

def test_extraction_keeps_local_hypotheses_and_single_letter_names():
    assert extract_symbol_heads("rw [hSgen]") == ["hSgen"]
    assert extract_symbol_heads("exact h") == ["h"]
    assert extract_symbol_heads("apply hSgen") == ["hSgen"]


def test_extraction_strips_rewrite_direction_and_ignores_compound_terms():
    assert extract_symbol_heads("rw [← ha, ⟨a, b⟩]") == ["ha"]
    assert extract_symbol_heads("rw [← hm, Finset.sdiff_singleton_eq_erase]") == [
        "hm", "Finset.sdiff_singleton_eq_erase"]


def test_extraction_handles_simp_using_and_nested_arguments():
    names = extract_symbol_heads("simp [h, Finset.prod_eq_one hr'.1] using hm")
    assert names == ["h", "Finset.prod_eq_one", "hm"]
    assert extract_symbol_heads(
        "rw [sum_Ico_by_parts f g (Nat.pos_of_ne_zero hn), sum_range_zero]") == [
        "sum_Ico_by_parts", "sum_range_zero"]


def test_extraction_does_not_treat_binders_or_keywords_as_lemmas():
    assert extract_symbol_heads("refine fun b ↦ ⟨fun i ↦ (hf i).choose, ?_⟩") == []
    assert extract_symbol_heads("simp [*]") == []
    assert extract_symbol_heads("intro h") == []
    # ``reassoc_of%`` is a term elaborator, not a declaration name.
    assert extract_symbol_heads("rw [h₁, reassoc_of% h₂, Hom.naturality]") == [
        "h₁", "Hom.naturality"]


def test_extraction_reads_the_leading_term_of_exact_and_apply():
    assert extract_symbol_heads("exact Nat.add_comm a b") == ["Nat.add_comm"]
    assert extract_symbol_heads("apply Function.Injective.comp") == ["Function.Injective.comp"]


# --- resolution -----------------------------------------------------------

def test_a_local_hypothesis_is_known_from_the_goal_state():
    assert "hSgen" in symbols_in_state("import Mathlib", "hSgen : S\n⊢ a ∈ S")
    index = frozenset()
    allowed = symbols_in_state("", "hSgen : S\n⊢ a ∈ S")
    assert filter_tactic("rw [hSgen]", index, allowed).allowed


def test_a_projection_of_a_local_hypothesis_is_known():
    allowed = symbols_in_state("", "hunit : IsUnit x\n⊢ y = z")
    result = filter_tactic("exact hunit.isStrictlyPositive (smul_nonneg hc.le ha.nonneg)",
                           frozenset(), allowed)
    assert result.allowed


def test_a_qualified_name_is_known_when_its_suffix_is_in_the_index():
    index = frozenset({"sum_eq_single"})
    assert is_known_symbol("Finset.sum_eq_single", index)
    assert filter_tactic("rw [Finset.sum_eq_single]", index).allowed


def test_an_unresolvable_name_is_refused():
    result = filter_tactic("rw [range_eq_Ico]", frozenset({"add_comm"}))
    assert not result.allowed
    assert result.unknown == ("range_eq_Ico",)


def test_a_tactic_without_lemma_arguments_is_always_allowed():
    assert filter_tactic("simp", frozenset()).allowed
    assert filter_tactic("rfl", frozenset()).allowed
    assert filter_tactic("simp_all", frozenset()).allowed


# --- index ----------------------------------------------------------------

def test_a_missing_index_is_an_error_only_when_required(tmp_path):
    missing = tmp_path / "missing.json"
    assert load_lemma_index(missing) == frozenset()
    with pytest.raises(FileNotFoundError, match="lemma index not found"):
        load_lemma_index(missing, required=True)


def test_a_gzip_index_loads_the_same_names(tmp_path):
    import gzip

    path = tmp_path / "lemma_index.json.gz"
    path.write_bytes(gzip.compress(json.dumps(["add_comm", "range_eq_Ico"]).encode()))
    assert load_lemma_index(path, required=True) == frozenset({"add_comm", "range_eq_Ico"})


# --- search integration ---------------------------------------------------

def test_filtering_is_off_by_default_and_the_candidate_reaches_lean():
    client = FakeClient()
    result = best_first(client, "theorem t : True", _predictor("rw [not_a_lemma_anywhere]"),
                        max_nodes=1, width=1)
    assert result.tactic_calls == 1
    assert result.rejected_unknown_lemmas == 0


def test_an_unknown_lemma_is_refused_without_a_lean_call(tmp_path):
    index = _write_index(tmp_path, {"add_comm"})
    client = FakeClient()
    result = best_first(client, "theorem t : True", _predictor("rw [not_a_lemma_anywhere]"),
                        max_nodes=1, width=1, filter_invalid_lemmas=True,
                        lemma_index_path=index)
    assert result.tactic_calls == 0
    assert result.rejected_unknown_lemmas == 1
    assert client.calls == []
    assert any(entry.get("rejected") == "unknown lemma" for entry in result.trace)


def test_a_local_hypothesis_is_not_refused_by_the_filter(tmp_path):
    index = _write_index(tmp_path, set())
    client = FakeClient()
    result = best_first(client, "theorem t (hSgen : True) : True", _predictor("exact hSgen"),
                        max_nodes=1, width=1, filter_invalid_lemmas=True,
                        lemma_index_path=index)
    assert result.rejected_unknown_lemmas == 0
    assert result.tactic_calls == 1


def test_filtering_with_a_missing_index_does_not_silently_run_unfiltered(tmp_path):
    with pytest.raises(FileNotFoundError, match="lemma index not found"):
        best_first(FakeClient(), "theorem t : True", _predictor("rfl"),
                   max_nodes=1, width=1, filter_invalid_lemmas=True,
                   lemma_index_path=tmp_path / "missing.json")
