import re
import unittest
from pathlib import Path

from neuralproof.data.info_tree import trace_file
from neuralproof.data.normalize_info_tree import normalize_trace
from neuralproof.data.preprocessing import classify_goal_scope
from neuralproof.goal_state import (canonical_goal_state, goal_count, split_goal_blocks)
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


class GoalStateUnitTests(unittest.TestCase):
    def test_canonical_form_drops_the_leading_blank_line(self):
        self.assertEqual(canonical_goal_state("\n⊢ True"), "⊢ True")
        self.assertEqual(canonical_goal_state("⊢ True\n"), "⊢ True")
        self.assertEqual(canonical_goal_state("\r\nn : Nat\r\n⊢ n = n\r\n"), "n : Nat\n⊢ n = n")

    def test_linter_messages_cannot_reach_the_goal_state(self):
        # Lean reports linter notices as their own messages; the client reads
        # the goal state from the `trace` message, so a notice about an unused
        # tactic or an unused binder cannot end up inside the captured state.
        run = LeanRun(0, ({"kind": "trace", "severity": "information", "data": "⊢ True"},
                           {"kind": "linter.unusedTactic", "severity": "warning",
                            "data": "Unused tactic linter: `all_goals trace_state` does nothing.\n\n"
                                    "Note: This linter can be disabled with `set_option linter.unusedTactic false`"},
                           {"kind": "hasSorry", "severity": "warning", "data": "declaration uses `sorry`"}))
        self.assertEqual(_goal_region(run), "⊢ True")

    def test_goal_blocks_split_on_case_headers(self):
        rendering = "case left\np : Prop\n⊢ p\ncase right\np : Prop\n⊢ q"
        self.assertEqual(split_goal_blocks(rendering),
                         ("case left\np : Prop\n⊢ p", "case right\np : Prop\n⊢ q"))
        self.assertEqual(split_goal_blocks("⊢ True"), ("⊢ True",))
        self.assertEqual(split_goal_blocks(""), ())

    def test_goal_count_counts_ordinary_and_conv_goals(self):
        self.assertEqual(goal_count("⊢ True"), 1)
        self.assertEqual(goal_count("| f x = f x"), 1)
        self.assertEqual(goal_count("case left\n⊢ p\ncase right\n⊢ q"), 2)

    def test_prompt_is_identical_for_mined_and_live_goal_states(self):
        mined = "\na b c : ℕ\n⊢ a / b / c = a / c / b"
        live = "a b c : ℕ\n⊢ a / b / c = a / c / b"
        self.assertEqual(format_tactic_prompt("import Lean", mined),
                         format_tactic_prompt("import Lean", live))


class GoalStateParityTests(unittest.TestCase):
    """The live client and the mined corpus must render goals identically."""

    @classmethod
    def setUpClass(cls):
        cls.client = LeanClient(timeout=60)
        cls.source = Path(__file__).parents[1] / "lean/NeuralProof/Samples.lean"
        cls.trace = trace_file(cls.source, timeout=180)
        cls.rows, _ = normalize_trace(cls.trace, cls.source)

    def _rows_for(self, declaration):
        rows = [row for row in self.rows if row["source_declaration"] == declaration]
        self.assertTrue(rows, f"no mined rows for {declaration}")
        return sorted(rows, key=lambda row: row["source_start"])

    def test_mined_and_live_goal_states_agree_for_the_first_tactic(self):
        for declaration in ("np_true", "np_add_zero", "np_pair"):
            rows = self._rows_for(declaration)
            header = _declaration_header(self.source, declaration)
            state = self.client.initial_state(header, rows[0]["context"])
            inspected = self.client.inspect(state)
            self.assertTrue(inspected.success, inspected.error)
            self.assertEqual(inspected.state.goal_state, _as_goal_state(rows[0]["goal_state"]))

    def test_live_result_state_matches_the_mined_result_state(self):
        rows = self._rows_for("np_pair")
        scopes = classify_goal_scope(rows)
        header = _declaration_header(self.source, "np_pair")
        state = self.client.initial_state(header, rows[0]["context"])
        for row, scope in zip(rows, scopes):
            inspected = self.client.inspect(state)
            self.assertTrue(inspected.success, inspected.error)
            result = self.client.apply(inspected.state, row["target_tactic"])
            self.assertTrue(result.success, result.error)
            if scope == "proof":
                self.assertEqual(inspected.state.goal_state, _as_goal_state(row["goal_state"]))
                self.assertEqual(result.state.goal_state, _as_goal_state(row["result_state"]))
            else:
                # A tactic inside a focus is mined with the goals of that focus
                # only, while the live client reports every open goal.
                mined = set(split_goal_blocks(_as_goal_state(row["goal_state"])))
                live = set(split_goal_blocks(inspected.state.goal_state))
                self.assertTrue(mined)
                self.assertTrue(mined < live, "the focused goal must be a strict subset of the live goals")
            state = result.state

    def test_focus_local_rows_are_reported(self):
        rows = self._rows_for("np_pair")
        scopes = classify_goal_scope(rows)
        focused = [row for row, scope in zip(rows, scopes) if scope == "focus"]
        self.assertEqual([row["target_tactic"] for row in focused], ["exact hp"])


if __name__ == "__main__":
    unittest.main()
