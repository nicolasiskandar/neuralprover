"""The completion boundary: where a model's answer starts and the prompt ends.

A base language model continues the prompt as a document, so a completion
usually begins by echoing the prompt back.  The tactic the model meant to
write is the first line that is not such an echo.  These cases pin that rule
down, because the earlier 0/50 result was an artifact of getting the
boundary wrong rather than a property of the model.
"""
import pytest

from neuralproof.models.tactics import BINDER, CASE_HEADER, GOAL_MARKER, PROMPT_LABELS, extract_tactic


def test_a_plain_tactic_is_returned():
    assert extract_tactic("simp\n") == "simp"


def test_a_leading_blank_line_is_skipped():
    # The model mirrors the prompt's blank line before answering.
    assert extract_tactic("\nsimp_all\n") == "simp_all"


def test_an_echoed_local_context_is_skipped():
    completion = "x : M\nhx : x ∈ s\n⊢ x = x\nsimp\n"
    assert extract_tactic(completion) == "simp"


def test_an_echoed_case_header_is_skipped():
    completion = "case inr\nM : Type u_1\ninst✝ : Submonoid.closure S\n"
    assert extract_tactic(completion) == ""


@pytest.mark.parametrize("label", PROMPT_LABELS)
def test_an_echoed_prompt_label_is_skipped(label):
    assert extract_tactic(f"{label}\nx : M\n") == ""


def test_a_conv_goal_marker_is_skipped():
    assert extract_tactic("| f x = f x\n") == ""


def test_a_completion_of_only_echoes_yields_no_tactic():
    assert extract_tactic("\nJ : Type w\ninst✝ : Category.{w} J\n⊢ P\n") == ""


def test_a_prose_answer_is_kept_for_lean_to_reject():
    # The filter is a budget saver, not a correctness claim: a line that
    # is not an echo is returned and Lean decides whether it is valid.
    prose = "1. Apply the definition of the category."
    assert extract_tactic(prose) == prose


def test_the_observed_model_completions_yield_no_tactic():
    # Raw completions captured from the pinned SmolLM2-135M base model.
    observed = [
        "J : Type w\ninst✝ : Category.{w', w} J\n⊢ ∀ {K : J ⥤ GrpCat}, PreservesLimit K uliftFunctor\nNext tactic:\n",
        "X✝ : BoolRing\n⊢ CommRingCat.ofHom (Hom.hom (𝟙 X✝)) = 𝟙 ↧↑X✝\n",
        "\nJ : Type w\ninst✝ : Category.{w', w} J\n⊢ ∀ {K : J ⥤ GrpCat}, PreservesLimit K uliftFunctor\n",
    ]
    for completion in observed:
        assert extract_tactic(completion) == "", completion


def test_a_whitespace_only_completion_yields_no_tactic():
    assert extract_tactic("   \n\t\n") == ""


def test_an_empty_completion_yields_no_tactic():
    assert extract_tactic("") == ""


def test_the_tactic_is_stripped_of_surrounding_space():
    assert extract_tactic("   simp   \n") == "simp"


def test_only_the_first_non_echo_line_is_returned():
    # A completion that answers and then continues the document still yields
    # the answer, not the rest of the document.
    assert extract_tactic("simp\nomega\n") == "simp"


def test_the_echo_patterns_are_the_ones_the_prompt_uses():
    # The filter and the prompt have to agree on what an echo looks like.
    assert "next tactic:" in PROMPT_LABELS
    assert "proof state:" in PROMPT_LABELS
    assert CASE_HEADER.match("case inr")
    assert not CASE_HEADER.match("cases inr")
    assert GOAL_MARKER.match("⊢ True")
    assert GOAL_MARKER.match("| f x = f x")
    assert not GOAL_MARKER.match("x : Nat")
    assert BINDER.match("x : Nat")
    assert not BINDER.match("⊢ True")
