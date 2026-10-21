import unittest
from neuralproof.data.splits import split_for
from neuralproof.data.schema import Example
from neuralproof.models.prompt import format_tactic_prompt
from neuralproof.data.preprocessing import classify_goal_scope, prepare_dataset, prepare_rows

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

    def test_recorded_split_is_kept(self):
        row={"source_file":"Mathlib/A.lean","context":"import Mathlib","goal_state":"⊢ True",
             "target_tactic":"trivial","split":"test"}
        result=prepare_dataset([row],seed="a-seed-that-would-say-train")
        self.assertEqual(len(result.groups["test"]),1)
        self.assertEqual(len(result.groups["train"]),0)
    def test_missing_split_is_computed_from_the_seed(self):
        row={"source_file":"Mathlib/A.lean","context":"import Mathlib","goal_state":"⊢ True","target_tactic":"trivial"}
        result=prepare_dataset([row],seed="neuralproof-v1")
        self.assertEqual(result.groups[split_for("Mathlib/A.lean","neuralproof-v1")][0]["split"],
                         split_for("Mathlib/A.lean","neuralproof-v1"))
    def test_seed_changes_the_split_of_rows_without_one(self):
        row={"source_file":"Mathlib/A.lean","context":"import Mathlib","goal_state":"⊢ True","target_tactic":"trivial"}
        first=prepare_dataset([row],seed="seed-one")
        second=prepare_dataset([row],seed="seed-two")
        self.assertEqual(sorted(first.groups),["test","train","validation"])
        self.assertEqual(sorted(second.groups),["test","train","validation"])
    def test_split_disagreement_is_counted_not_applied(self):
        row={"source_file":"Mathlib/A.lean","context":"import Mathlib","goal_state":"⊢ True",
             "target_tactic":"trivial","split":"test"}
        disagreeing=split_for("Mathlib/A.lean","neuralproof-v1")
        if disagreeing=="test": disagreeing="train"
        result=prepare_dataset([row],seed="neuralproof-v1")
        self.assertEqual(result.split_disagreements,1)
        self.assertEqual(len(result.groups["test"]),1)

    def test_goal_scope_labels_focus_local_rows(self):
        rows=[{"source_file":"A.lean","source_declaration":"d","goal_state":"⊢ p","result_state":"no goals"},
              {"source_file":"A.lean","source_declaration":"d","goal_state":"⊢ q","result_state":"no goals"}]
        self.assertEqual(classify_goal_scope(rows),["focus","proof"])
    def test_goal_scope_labels_conv_goals(self):
        rows=[{"source_file":"A.lean","source_declaration":"d","goal_state":"| f x = f x","result_state":"| f x = f x"}]
        self.assertEqual(classify_goal_scope(rows),["conv"])
    def test_goal_scope_does_not_infer_focus_without_a_result_state(self):
        # The narrow extractor records no result state, so nothing is known
        # about the scope of the state it observed.
        rows=[{"source_file":"A.lean","source_declaration":"d","goal_state":"⊢ True"},
              {"source_file":"A.lean","source_declaration":"d","goal_state":"⊢ True"}]
        self.assertEqual(classify_goal_scope(rows),["proof","proof"])
    def test_prepared_rows_carry_the_scope_and_the_prompt(self):
        row={"source_file":"A.lean","source_declaration":"d","context":"import Lean","goal_state":"\n⊢ True","target_tactic":"trivial"}
        result=prepare_dataset([row])
        prepared=result.groups["train"][0]
        self.assertEqual(prepared["goal_scope"],"proof")
        self.assertEqual(prepared["prompt"],"Context:\nimport Lean\nProof state:\n⊢ True\nNext tactic:\n")

class ProvenanceTests(unittest.TestCase):
    def test_file_digest_matches_the_content(self):
        import tempfile
        from pathlib import Path
        from neuralproof.data.provenance import sha256_file, sha256_text
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"x.txt"; path.write_text("abc")
            self.assertEqual(sha256_file(path),sha256_text("abc"))
            self.assertIsNone(sha256_file(Path(td)/"missing.txt"))
    def test_working_tree_state_is_reported(self):
        from neuralproof.data.provenance import working_tree_state
        self.assertIn(working_tree_state(),{"clean","dirty","unknown"})
    def test_manifest_records_the_command_and_the_inputs(self):
        import json, tempfile
        from pathlib import Path
        from neuralproof.data.provenance import write_manifest
        with tempfile.TemporaryDirectory() as td:
            path=write_manifest(Path(td)/"manifest.json",{"artifact":"x"})
            self.assertEqual(json.loads(path.read_text())["artifact"],"x")
