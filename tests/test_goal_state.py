"""The goal state: one rendering for the mined corpus and the live client."""
import re
from pathlib import Path

import pytest

from neuralproof.data.info_tree import trace_file
from neuralproof.data.normalize_info_tree import normalize_trace
from neuralproof.data.preprocessing import classify_goal_scope
from neuralproof.goal_state import canonical_goal_state, goal_count, split_goal_blocks
from neuralproof.lean.client import LeanClient, LeanRun, _goal_region
from neuralproof.models.prompt import format_tactic_prompt


def _declaration_header(source: Path, declaration: str) -> str:
    """Return the theorem header of a declaration, without its proof."""
    name = declaration.rsplit(".", 1)[-1]
    for line in source.read_text().splitlines():
        match = re.match(r"^(?:protected\s+)?(?:private\s+)?(?:theorem|lemma)\s+([\w.']+)", line)
        if match and match.group(1).rsplit(".", 1)[-1] == name and ":=" in line:
            return line.split(":= by", 1)[0].rstrip()
    raise AssertionError(f"no header found for {declaration} in {source}")


def _as_goal_state(rendering: str) -> str:
    """Normalize a rendering for comparison; Lean prints `no goals` for none."""
    canonical = canonical_goal_state(rendering)
    return "" if canonical == "no goals" else canonical


# --- the canonical form ----------------------------------------------------

def test_canonical_form_drops_the_leading_blank_line():
    assert canonical_goal_state("\n⊢ True") == "⊢ True"
    assert canonical_goal_state("⊢ True\n") == "⊢ True"
    assert canonical_goal_state("\r\nn : Nat\r\n⊢ n = n\r\n") == "n : Nat\n⊢ n = n"


def test_linter_messages_cannot_reach_the_goal_state():
    # Lean reports linter notices as their own messages; the client reads
    # the goal state from the `trace` message, so a notice about an unused
    # tactic or an unused binder cannot end up inside the captured state.
    run = LeanRun(0, ({"kind": "trace", "severity": "information", "data": "⊢ True"},
                       {"kind": "linter.unusedTactic", "severity": "warning",
                        "data": "Unused tactic linter: `all_goals trace_state` does nothing.\n\n"
                                "Note: This linter can be disabled with `set_option linter.unusedTactic false`"},
                       {"kind": "hasSorry", "severity": "warning", "data": "declaration uses `sorry`"}))
    assert _goal_region(run) == "⊢ True"


def test_goal_blocks_split_on_case_headers():
    rendering = "case left\np : Prop\n⊢ p\ncase right\np : Prop\n⊢ q"
    assert split_goal_blocks(rendering) == ("case left\np : Prop\n⊢ p", "case right\np : Prop\n⊢ q")
    assert split_goal_blocks("⊢ True") == ("⊢ True",)
    assert split_goal_blocks("") == ()


def test_goal_count_counts_ordinary_and_conv_goals():
    assert goal_count("⊢ True") == 1
    assert goal_count("| f x = f x") == 1
    assert goal_count("case left\n⊢ p\ncase right\n⊢ q") == 2


def test_prompt_is_identical_for_mined_and_live_goal_states():
    mined = "\na b c : ℕ\n⊢ a / b / c = a / c / b"
    live = "a b c : ℕ\n⊢ a / b / c = a / c / b"
    assert format_tactic_prompt("import Lean", mined) == \
        format_tactic_prompt("import Lean", live)


def test_an_empty_state_has_no_goals():
    assert goal_count("") == 0
    assert goal_count("no goals") == 0
    assert split_goal_blocks("no goals") == ("no goals",)


# --- the parity between the mined corpus and the live client --------------

@pytest.fixture(scope="module")
def lean_client():
    return LeanClient(timeout=60)


@pytest.fixture(scope="module")
def sample_source():
    return Path(__file__).parents[1] / "lean/NeuralProof/Samples.lean"


@pytest.fixture(scope="module")
def mined_rows(sample_source):
    trace = trace_file(sample_source, timeout=180)
    rows, _ = normalize_trace(trace, sample_source)
    return rows


def rows_for(rows, declaration):
    selected = [row for row in rows if row["source_declaration"] == declaration]
    assert selected, f"no mined rows for {declaration}"
    return sorted(selected, key=lambda row: row["source_start"])


@pytest.mark.lean
def test_mined_and_live_goal_states_agree_for_the_first_tactic(lean_client, sample_source,
                                                               mined_rows):
    for declaration in ("np_true", "np_add_zero", "np_pair"):
        selected = rows_for(mined_rows, declaration)
        header = _declaration_header(sample_source, declaration)
        state = lean_client.initial_state(header, selected[0]["context"])
        inspected = lean_client.inspect(state)
        assert inspected.success, inspected.error
        assert inspected.state.goal_state == _as_goal_state(selected[0]["goal_state"])


@pytest.mark.lean
def test_live_result_state_matches_the_mined_result_state(lean_client, sample_source, mined_rows):
    selected = rows_for(mined_rows, "np_pair")
    scopes = classify_goal_scope(selected)
    header = _declaration_header(sample_source, "np_pair")
    state = lean_client.initial_state(header, selected[0]["context"])
    for row, scope in zip(selected, scopes):
        inspected = lean_client.inspect(state)
        assert inspected.success, inspected.error
        result = lean_client.apply(inspected.state, row["target_tactic"])
        assert result.success, result.error
        if scope == "proof":
            assert inspected.state.goal_state == _as_goal_state(row["goal_state"])
            assert result.state.goal_state == _as_goal_state(row["result_state"])
        else:
            # A tactic inside a focus is mined with the goals of that focus
            # only, while the live client reports every open goal.
            mined = set(split_goal_blocks(_as_goal_state(row["goal_state"])))
            live = set(split_goal_blocks(inspected.state.goal_state))
            assert mined
            assert mined < live, "the focused goal must be a strict subset of the live goals"
        state = result.state


@pytest.mark.lean
def test_focus_local_rows_are_reported(mined_rows):
    selected = rows_for(mined_rows, "np_pair")
    scopes = classify_goal_scope(selected)
    focused = [row for row, scope in zip(selected, scopes) if scope == "focus"]
    assert [row["target_tactic"] for row in focused] == ["exact hp"]
