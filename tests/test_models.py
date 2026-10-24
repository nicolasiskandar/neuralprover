"""The model side: the prompt, the training budget, and the rows to train on."""
import pytest

from neuralproof.models.finetune import resolve_max_steps, select_training_rows


def test_the_training_prompt_and_the_evaluation_prompt_are_identical():
    from neuralproof.lean.client import ProofState
    from neuralproof.models.prompt import format_tactic_prompt
    # A mined row reaches the trainer as a context and a goal state, and
    # reaches the evaluator wrapped in a ProofState.  Before the goal
    # state was canonicalized the two prompts differed by a blank line,
    # which is what made the earlier 0/50 a harness artifact.
    row = {"context": "import Mathlib\n\nopen scoped BigOperators",
           "goal_state": "\ncase h\nn : Nat\n⊢ n = n\n"}
    training_prompt = format_tactic_prompt(row["context"], row["goal_state"])
    state = ProofState(theorem="", context=row["context"], goals=(row["goal_state"],))
    evaluation_prompt = format_tactic_prompt(state.context, state.goal_state)
    assert training_prompt == evaluation_prompt


def test_the_prompt_has_no_blank_line_after_the_state_label():
    from neuralproof.models.prompt import format_tactic_prompt
    prompt = format_tactic_prompt("import Lean", "\n⊢ True\n")
    assert "Proof state:\n\n" not in prompt
    assert prompt.endswith("Next tactic:\n")


# --- the step budget -------------------------------------------------------

def test_an_unbounded_run_uses_the_transformers_default():
    # `TrainingArguments` stops the loop when `global_step >= max_steps`,
    # so an unbounded run has to pass the transformers default of -1.
    assert resolve_max_steps(-1) == -1


def test_a_positive_budget_is_kept():
    assert resolve_max_steps(100) == 100


def test_a_zero_budget_is_rejected():
    # 0 would end the run after its first step while looking like an
    # unbounded request, which is how a full-epoch run was once reduced
    # to one step.
    with pytest.raises(ValueError, match="first step"):
        resolve_max_steps(0)


def test_a_budget_below_minus_one_is_rejected():
    with pytest.raises(ValueError):
        resolve_max_steps(-2)


def test_the_budget_reaches_the_trainer_unchanged():
    # `TrainingArguments` keeps the value it is given, and the trainer
    # derives the number of steps from it: `-1` means "as many steps as
    # the epochs need", any other non-negative value is a hard limit.
    transformers = pytest.importorskip("transformers")
    arguments = transformers.TrainingArguments
    assert arguments(output_dir="/tmp/neuralproof-test", max_steps=resolve_max_steps(-1)).max_steps == -1
    assert arguments(output_dir="/tmp/neuralproof-test", max_steps=resolve_max_steps(100)).max_steps == 100


def test_a_zero_budget_is_rejected_before_the_training_stack_is_needed():
    # The check happens before the torch import, so a bad budget is
    # reported as a bad budget even on a machine without the extras.
    from neuralproof.models.finetune import train
    with pytest.raises(ValueError, match="first step"):
        train("data.jsonl", "model", "out", max_steps=0)


# --- which rows are trained on --------------------------------------------

def test_rows_of_another_scope_are_dropped():
    rows = [{"goal_scope": "proof"}, {"goal_scope": "focus"}, {"goal_scope": "conv"}]
    kept, dropped = select_training_rows(rows, "proof")
    assert [row["goal_scope"] for row in kept] == ["proof"]
    assert dropped == 2


def test_rows_without_a_scope_marker_are_kept():
    # The narrow extractor records proof-global states but writes no scope
    # marker, so an unmarked row is a proof-scope row.
    rows = [{"goal_scope": "proof"}, {"target_tactic": "trivial"}]
    kept, dropped = select_training_rows(rows, "proof")
    assert len(kept) == 2
    assert dropped == 0


def test_an_empty_scope_keeps_every_row():
    rows = [{"goal_scope": "proof"}, {"goal_scope": "focus"}]
    kept, dropped = select_training_rows(rows, "")
    assert len(kept) == 2
    assert dropped == 0


def test_a_focus_scope_keeps_the_focus_rows():
    rows = [{"goal_scope": "proof"}, {"goal_scope": "focus"}]
    kept, dropped = select_training_rows(rows, "focus")
    assert [row["goal_scope"] for row in kept] == ["focus"]
    assert dropped == 1


def test_the_scope_filter_does_not_mutate_its_input():
    rows = [{"goal_scope": "proof"}, {"goal_scope": "focus"}]
    select_training_rows(rows, "proof")
    assert len(rows) == 2
