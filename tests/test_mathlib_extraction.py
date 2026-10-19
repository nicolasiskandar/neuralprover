import unittest
from pathlib import Path
from neuralproof.data.extraction import extract_mathlib_file, MATHLIB_REVISION
from neuralproof.data.info_tree import trace_file
from neuralproof.data.normalize_info_tree import normalize_trace, validate_trace_examples
from neuralproof.lean.client import LeanClient

class MathlibExtractionTests(unittest.TestCase):
    def test_native_info_tree_driver_captures_goals(self):
        source=Path(__file__).parents[1]/"lean/NeuralProof/Samples.lean"
        result=trace_file(source,timeout=120)
        self.assertEqual(result["backend"],"lean4_info_tree")
        self.assertGreater(result["tactic_nodes"],0)
        self.assertTrue(any("n + 0 = n" in t["goal_state"] for t in result["traces"]))
        self.assertGreater(result["command_nodes"],0)
        self.assertTrue(any(c["syntax_kind"]=="Lean.Parser.Command.declaration" for c in result["commands"]))

    def test_info_tree_normalizer_deduplicates_wrappers_and_tracks_steps(self):
        source=Path(__file__).parents[1]/"lean/NeuralProof/Samples.lean"
        trace=trace_file(source,timeout=120)
        rows,stats=normalize_trace(trace,source)
        self.assertEqual(stats["output_examples"],5)
        self.assertEqual([r["target_tactic"].splitlines()[0] for r in rows],
                         ["trivial","rfl","constructor","exact hp","exact hq"])
        self.assertEqual([r["source_declaration"] for r in rows],
                         ["np_true","np_add_zero","np_pair","np_pair","np_pair"])
        self.assertTrue(all(r["goal_state"].strip() for r in rows))
        self.assertTrue(all(r["context"].startswith("import Lean") for r in rows))
        self.assertGreater(stats["deduplicated_nodes"],0)

    def test_sample_trajectory_prefixes_replay_with_lean(self):
        source=Path(__file__).parents[1]/"lean/NeuralProof/Samples.lean"
        trace=trace_file(source,timeout=120)
        rows,_=normalize_trace(trace,source)
        checked,stats=validate_trace_examples(trace,source,rows,timeout=60)
        self.assertEqual(len(checked),5)
        self.assertEqual(stats["declarations_count"],3)
        self.assertEqual(stats["validation_counts"],{"replayed":3})
        self.assertTrue(all(r["validation"]=="replayed" for r in checked))
        self.assertTrue(all(r["validation_harness_contains_sorry"] for r in checked))

    def test_real_mathlib_tactic_is_replayed_and_verified(self):
        root=Path(__file__).parents[1]/"lean/.lake/packages/mathlib"
        if not (root/"Mathlib/Data/Nat/Basic.lean").exists(): self.fail("run `cd lean && lake update` before Mathlib integration tests")
        rows,stats=extract_mathlib_file(LeanClient(),root,"Mathlib/Data/Nat/Basic.lean",limit=3)
        self.assertEqual(stats["source_revision"],MATHLIB_REVISION)
        self.assertEqual(len(rows),1)
        self.assertEqual({x["source_declaration"] for x in rows},{"Nat.div_right_comm"})
        self.assertIn("namespace Nat",rows[0]["context"]); self.assertIn("open Function",rows[0]["context"])
        self.assertIn("Mathlib.Data.Nat",rows[0]["context"])
        self.assertNotIn("import Mathlib\n",rows[0]["context"])
        self.assertEqual(rows[0]["theorem_id"],"np_mined_Mathlib_Data_Nat_Basic_Nat_div_right_comm")
        self.assertEqual(rows[0]["target_tactic"],"rw [Nat.div_div_eq_div_mul, Nat.mul_comm, ← Nat.div_div_eq_div_mul]")
    def test_info_tree_normalizer_keeps_source_rewrite_and_pre_tactic_state(self):
        root=Path(__file__).parents[1]/"lean/.lake/packages/mathlib"
        source=root/"Mathlib/Data/Nat/Basic.lean"
        trace=trace_file(source,timeout=120)
        rows,_=normalize_trace(trace,source)
        row=next(r for r in rows if r["source_declaration"]=="Nat.div_right_comm")
        self.assertEqual(row["target_tactic"],"rw [Nat.div_div_eq_div_mul, Nat.mul_comm, ← Nat.div_div_eq_div_mul]")
        self.assertEqual(row["syntax_kind"],"Lean.Parser.Tactic.rewriteSeq")
        self.assertIn("a / b / c",row["goal_state"])
        self.assertEqual(row["source_line"],59)
        self.assertNotIn("import Mathlib\n",row["context"])
    def test_missing_prior_declaration_context_is_reported(self):
        root=Path(__file__).parents[1]/"lean/.lake/packages/mathlib"
        mv,ms=extract_mathlib_file(LeanClient(),root,"Mathlib/Algebra/MvPolynomial/Basic.lean",1,"notMem_support_iff")
        group,gs=extract_mathlib_file(LeanClient(),root,"Mathlib/Algebra/Group/Basic.lean",1,"mul_div_mul_left_eq_div")
        self.assertEqual((len(mv),len(group)),(0,0))
        self.assertEqual(ms["context_policy"],"source_imports_and_active_context_excluding_target")
        self.assertEqual(gs["context_policy"],"source_imports_and_active_context_excluding_target")
        self.assertIn("tactic replay did not close goal",[x["reason"] for x in ms["failures"]])
        self.assertIn("tactic replay did not close goal",[x["reason"] for x in gs["failures"]])
    def test_namespaced_declarations_get_unique_ids(self):
        root=Path(__file__).parents[1]/"lean/.lake/packages/mathlib"
        rows,stats=extract_mathlib_file(LeanClient(),root,"Mathlib/Algebra/BigOperators/ModEq.lean",5,"listSum_map")
        self.assertEqual({x["source_declaration"] for x in rows},{"Nat.ModEq.listSum_map","Int.ModEq.listSum_map"})
        self.assertEqual(len({x["theorem_id"] for x in rows}),2)
        self.assertEqual(len({x["theorem"].split()[1] for x in rows}),2)

if __name__=="__main__": unittest.main()
