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
        context="import Mathlib"
        s=self.client.initial_state("theorem mathlib_test (n : Nat) : n + 0 = n",context)
        r=self.client.apply(s,"simp")
        self.assertTrue(r.success); self.assertTrue(r.completed)
        v=self.client.verify(self.client.render_proof(r.state),context=context)
        self.assertTrue(v.verified); self.assertLessEqual(set(v.axioms),{"propext","Classical.choice","Quot.sound"})
    def test_invalid_tactic(self): self.assertFalse(self.client.apply(self.client.initial_state("theorem bad : True"),"not_a_tactic").success)
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
