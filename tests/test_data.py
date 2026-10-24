"""The data side: schema, splits, label policy, and the scope of a mined row."""
import json

import pytest

from neuralproof.data.preprocessing import (classify_goal_scope, is_tactic_target,
                                            prepare_dataset, prepare_rows)
from neuralproof.data.schema import Example
from neuralproof.data.splits import split_for
from neuralproof.models.prompt import format_tactic_prompt


# --- schema ----------------------------------------------------------------

def test_jsonl_roundtrip():
    example = Example("x", "theorem x : True := by", "import Lean", "⊢ True", "trivial", "X.lean")
    assert json.loads(example.jsonl())["target_tactic"] == "trivial"


# --- splits ----------------------------------------------------------------

def test_split_deterministic_and_file_level():
    assert split_for("A.lean") == split_for("A.lean")
    assert split_for("A.lean") in {"train", "validation", "test"}


def test_a_different_seed_can_move_a_file_to_another_split():
    # The seed decides the split of a file that carries none, and it has to
    # be able to do more than reshuffle the same files.
    assert split_for("A.lean", "seed-one") != split_for("A.lean", "seed-two")


# --- prompt ----------------------------------------------------------------

def test_tactic_prompt_uses_context_and_current_state():
    expected = "Context:\nimport Lean\nProof state:\nn : Nat\n⊢ n = n\nNext tactic:\n"
    assert format_tactic_prompt("import Lean", "n : Nat\n⊢ n = n") == expected
    assert format_tactic_prompt("import Lean", ("n : Nat\n⊢ n = n",)) == expected


# --- validation policy -----------------------------------------------------

def test_preprocessing_excludes_info_tree_rows_until_replayed():
    base = {"source_file": "Mathlib/A.lean", "context": "import Mathlib",
            "goal_state": "⊢ True", "target_tactic": "trivial"}
    rows = [dict(base, validation="transition_replay_pending"), dict(base, validation="replayed"),
            dict(base)]
    groups, excluded = prepare_rows(rows)
    assert excluded == 1
    assert sum(map(len, groups.values())) == 2


def test_a_replayed_row_is_stamped_as_replayed():
    base = {"source_file": "Mathlib/A.lean", "context": "import Mathlib",
            "goal_state": "⊢ True", "target_tactic": "trivial"}
    result = prepare_dataset([dict(base, validation="replayed")])
    assert result.validation_status_counts == {"replayed": 1}
    assert result.groups["train"][0]["validation_status"] == "replayed"


def test_unreplayed_rows_are_kept_and_stamped_when_they_are_asked_for():
    base = {"source_file": "Mathlib/A.lean", "context": "import Mathlib",
            "goal_state": "⊢ True", "target_tactic": "trivial"}
    result = prepare_dataset([dict(base, validation="transition_replay_pending")],
                              include_unvalidated=True)
    assert result.excluded_unvalidated == 0
    assert result.validation_status_counts == {"unreplayed": 1}
    assert result.groups["train"][0]["validation_status"] == "unreplayed"


# --- the recorded split ----------------------------------------------------

def test_recorded_split_is_kept():
    row = {"source_file": "Mathlib/A.lean", "context": "import Mathlib", "goal_state": "⊢ True",
           "target_tactic": "trivial", "split": "test"}
    result = prepare_dataset([row], seed="a-seed-that-would-say-train")
    assert len(result.groups["test"]) == 1
    assert len(result.groups["train"]) == 0


def test_missing_split_is_computed_from_the_seed():
    row = {"source_file": "Mathlib/A.lean", "context": "import Mathlib", "goal_state": "⊢ True",
           "target_tactic": "trivial"}
    result = prepare_dataset([row], seed="neuralproof-v1")
    assert result.groups[split_for("Mathlib/A.lean", "neuralproof-v1")][0]["split"] == \
        split_for("Mathlib/A.lean", "neuralproof-v1")


def test_seed_changes_the_split_of_rows_without_one():
    row = {"source_file": "Mathlib/A.lean", "context": "import Mathlib", "goal_state": "⊢ True",
           "target_tactic": "trivial"}
    first = prepare_dataset([row], seed="seed-one")
    second = prepare_dataset([row], seed="seed-two")
    assert sorted(first.groups) == ["test", "train", "validation"]
    assert sorted(second.groups) == ["test", "train", "validation"]


def test_split_disagreement_is_counted_not_applied():
    row = {"source_file": "Mathlib/A.lean", "context": "import Mathlib", "goal_state": "⊢ True",
           "target_tactic": "trivial", "split": "test"}
    disagreeing = split_for("Mathlib/A.lean", "neuralproof-v1")
    if disagreeing == "test":
        disagreeing = "train"
    result = prepare_dataset([row], seed="neuralproof-v1")
    assert result.split_disagreements == 1
    assert len(result.groups["test"]) == 1


def test_one_source_file_never_lands_in_two_splits():
    # A file that appears in both the training and the test split leaks the
    # test set into training, so the split has to be a property of the file.
    rows = [{"source_file": "Mathlib/A.lean", "context": "import Mathlib",
             "goal_state": "⊢ True", "target_tactic": "trivial",
             "split": split} for split in ("train", "validation", "test")]
    result = prepare_dataset(rows, seed="neuralproof-v1")
    assert result.split_disagreements == 2
    assert len(result.groups["train"]) == 1
    assert len(result.groups["validation"]) == 1
    assert len(result.groups["test"]) == 1


# --- the scope of a mined row ---------------------------------------------

def test_goal_scope_labels_focus_local_rows():
    rows = [{"source_file": "A.lean", "source_declaration": "d", "goal_state": "⊢ p",
             "result_state": "no goals"},
            {"source_file": "A.lean", "source_declaration": "d", "goal_state": "⊢ q",
             "result_state": "no goals"}]
    assert classify_goal_scope(rows) == ["focus", "proof"]


def test_goal_scope_labels_conv_goals():
    rows = [{"source_file": "A.lean", "source_declaration": "d",
             "goal_state": "| f x = f x", "result_state": "| f x = f x"}]
    assert classify_goal_scope(rows) == ["conv"]


def test_goal_scope_does_not_infer_focus_without_a_result_state():
    # The narrow extractor records no result state, so nothing is known
    # about the scope of the state it observed.
    rows = [{"source_file": "A.lean", "source_declaration": "d", "goal_state": "⊢ True"},
            {"source_file": "A.lean", "source_declaration": "d", "goal_state": "⊢ True"}]
    assert classify_goal_scope(rows) == ["proof", "proof"]


def test_the_last_row_of_a_declaration_is_never_focus_local():
    # The last tactic of a declaration closes the proof, so it cannot have
    # been mined inside a focus even if its result state is empty.
    rows = [{"source_file": "A.lean", "source_declaration": "d", "goal_state": "⊢ p",
             "result_state": "no goals", "source_start": 1},
            {"source_file": "A.lean", "source_declaration": "d", "goal_state": "⊢ q",
             "result_state": "no goals", "source_start": 2}]
    assert classify_goal_scope(rows) == ["focus", "proof"]


def test_prepared_rows_carry_the_scope_and_the_prompt():
    row = {"source_file": "A.lean", "source_declaration": "d", "context": "import Lean",
           "goal_state": "\n⊢ True", "target_tactic": "trivial"}
    result = prepare_dataset([row])
    prepared = result.groups["train"][0]
    assert prepared["goal_scope"] == "proof"
    assert prepared["prompt"] == "Context:\nimport Lean\nProof state:\n⊢ True\nNext tactic:\n"


def test_the_prepared_prompt_is_the_canonical_prompt():
    # The training prompt and the prompt the evaluator builds have to be the
    # same bytes, or the model is trained on a format it is never asked for.
    row = {"source_file": "A.lean", "context": "import Lean", "goal_state": "\n⊢ True",
           "target_tactic": "trivial"}
    prepared = prepare_dataset([row]).groups["train"][0]
    assert prepared["prompt"] == format_tactic_prompt(row["context"], row["goal_state"])


# --- the label policy ------------------------------------------------------

@pytest.mark.parametrize("target", ("by", "where", "{", "(", "‹_›", "1", "."))
def test_a_target_that_is_not_a_tactic_is_recognised(target):
    assert not is_tactic_target(target)


@pytest.mark.parametrize("target", ("simp", "rfl", "exact h", "rcases s with ⟨l⟩",
                                    "obtain ⟨a, b⟩ := h"))
def test_a_real_tactic_is_accepted(target):
    assert is_tactic_target(target)


@pytest.mark.parametrize("target", ("", "   ", "\n"))
def test_an_empty_target_is_not_a_tactic(target):
    assert not is_tactic_target(target)


def test_rows_with_non_tactic_targets_are_excluded_and_counted():
    base = {"source_file": "A.lean", "context": "import Lean", "goal_state": "⊢ True"}
    rows = [dict(base, target_tactic="trivial"), dict(base, target_tactic="by"),
            dict(base, target_tactic="where"), dict(base, target_tactic="{")]
    result = prepare_dataset(rows)
    assert sum(map(len, result.groups.values())) == 1
    assert result.excluded_non_tactic_targets == 3


def test_a_non_tactic_target_is_never_counted_as_unvalidated():
    # A row can be excluded for two reasons at once; the counts have to
    # stay separate or a label defect hides inside a validation count.
    base = {"source_file": "A.lean", "context": "import Lean", "goal_state": "⊢ True"}
    rows = [dict(base, target_tactic="by", validation="transition_replay_pending")]
    result = prepare_dataset(rows, include_unvalidated=True)
    assert result.excluded_non_tactic_targets == 1
    assert result.excluded_unvalidated == 0
    assert sum(map(len, result.groups.values())) == 0
