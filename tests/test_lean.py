import unittest
from neuralproof.lean.client import LeanClient

class LeanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.client=LeanClient(timeout=15)
    def test_doctor(self): self.assertIn("Lean (version 4.35.0",self.client.doctor())
    def test_verified_end_to_end(self):
        s=self.client.initial_state("theorem test_true : True")
        r=self.client.apply(s,"exact True.intro")
        self.assertTrue(r.success); self.assertTrue(r.completed)
        self.assertTrue(self.client.verify(self.client.render_proof(r.state)).verified)
    def test_mathlib_context_and_kernel_verification(self):
        # `import Mathlib` loads the whole library's oleans; the class-wide
        # 15 s timeout is marginal for that under load, so this case uses a
        # client with its own budget.
        client=LeanClient(timeout=120)
        context="import Mathlib"
        s=client.initial_state("theorem mathlib_test (n : Nat) : n + 0 = n",context)
        r=client.apply(s,"simp")
        self.assertTrue(r.success,r.error); self.assertTrue(r.completed,r.error)
        v=client.verify(client.render_proof(r.state),context=context)
        self.assertTrue(v.verified,v.output); self.assertLessEqual(set(v.axioms),{"propext","Classical.choice","Quot.sound"})
    def test_invalid_tactic(self): self.assertFalse(self.client.apply(self.client.initial_state("theorem bad : True"),"not_a_tactic").success)
    def test_unknown_identifier_is_reported_as_a_failure(self):
        result=self.client.apply(self.client.initial_state("theorem bad : True"),"exact Nat.sorry")
        self.assertFalse(result.success); self.assertIsNone(result.state); self.assertFalse(result.completed)
        self.assertIn("Unknown constant",result.error)
    def test_type_mismatch_is_reported_as_a_failure(self):
        result=self.client.apply(self.client.initial_state("theorem bad : True"),"exact (5 : Nat)")
        self.assertFalse(result.success); self.assertIsNone(result.state)
        self.assertIn("Type mismatch",result.error)
    def test_a_failing_tactic_leaves_the_previous_goals_untouched(self):
        state=self.client.inspect(self.client.initial_state("theorem bad : True")).state
        self.assertEqual(state.goal_state,"⊢ True")
        result=self.client.apply(state,"exact (5 : Nat)")
        self.assertFalse(result.success); self.assertIsNone(result.state)
        self.assertEqual(state.goal_state,"⊢ True")
    def test_inspect_rejects_an_ill_typed_declaration(self):
        state=self.client.initial_state("theorem bad : Nat := by exact True.intro")
        result=self.client.inspect(state)
        self.assertFalse(result.success); self.assertIsNone(result.state); self.assertTrue(result.error)
    def test_linter_notices_do_not_reach_the_goal_state(self):
        # An unused binder makes Lean emit a linter notice; the captured goal
        # state must contain the goal only.
        state=self.client.initial_state("theorem unused_binder (n : Nat) : True")
        inspected=self.client.inspect(state)
        self.assertTrue(inspected.success,inspected.error)
        self.assertEqual(inspected.state.goal_state,"n : Nat\n⊢ True")
    def test_unused_binder_does_not_break_kernel_verification(self):
        # Lean's unused-variable linter prints a bracketed hint; it must not be
        # mistaken for an axiom dependency.
        result=self.client.verify("theorem np_unused (n : Nat) : True := by trivial")
        self.assertTrue(result.verified,result.output)
        self.assertEqual(result.axioms,())
    def test_multiple_goals_and_placeholder_audit(self):
        s=self.client.initial_state("theorem pair (p q : Prop) (hp : p) (hq : q) : p ∧ q")
        a=self.client.apply(s,"constructor"); self.assertTrue(a.success); self.assertFalse(a.completed)
        b=self.client.apply(a.state,"exact hp"); self.assertTrue(b.success); self.assertFalse(b.completed)
        c=self.client.apply(b.state,"exact hq"); self.assertTrue(c.completed)
        self.assertTrue(self.client.verify(self.client.render_proof(c.state)).verified)
        self.assertFalse(self.client.verify("theorem invalid : True := by\n  sorry").verified)
    def test_unexpected_axiom_rejected(self):
        result=self.client.verify("axiom fabricated : True\ntheorem unsound : True := fabricated")
        self.assertFalse(result.verified); self.assertIn("fabricated",result.axioms)
    def test_subprocess_timeout(self):
        client=LeanClient(timeout=0.000001)
        result=client.apply(client.initial_state("theorem slow : True"),"trivial")
        self.assertFalse(result.success); self.assertIn("timed out",result.error)

if __name__=="__main__": unittest.main()
