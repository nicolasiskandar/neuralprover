import unittest
from neuralproof.data.splits import split_for
from neuralproof.data.schema import Example
from neuralproof.models.prompt import format_tactic_prompt
from neuralproof.data.preprocessing import prepare_rows

class DataTests(unittest.TestCase):
    def test_jsonl_roundtrip(self):
        import json
        e=Example("x","theorem x : True := by","import Lean","⊢ True","trivial","X.lean")
        self.assertEqual(json.loads(e.jsonl())["target_tactic"],"trivial")
    def test_split_deterministic_and_file_level(self):
        self.assertEqual(split_for("A.lean"),split_for("A.lean")); self.assertIn(split_for("A.lean"),{"train","validation","test"})
    def test_tactic_prompt_uses_context_and_current_state(self):
        self.assertEqual(format_tactic_prompt("import Lean", "n : Nat\n⊢ n = n"),
                         "Context:\nimport Lean\nProof state:\nn : Nat\n⊢ n = n\nNext tactic:\n")
        self.assertEqual(format_tactic_prompt("import Lean", ("n : Nat\n⊢ n = n",)),
                         "Context:\nimport Lean\nProof state:\nn : Nat\n⊢ n = n\nNext tactic:\n")
    def test_preprocessing_excludes_info_tree_rows_until_replayed(self):
        base={"source_file":"Mathlib/A.lean","context":"import Mathlib","goal_state":"⊢ True","target_tactic":"trivial"}
        rows=[dict(base,validation="transition_replay_pending"),dict(base,validation="replayed"),dict(base)]
        groups,excluded=prepare_rows(rows)
        self.assertEqual(excluded,1)
        self.assertEqual(sum(map(len,groups.values())),2)
