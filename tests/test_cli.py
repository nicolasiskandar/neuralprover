import unittest
from neuralproof.cli import parse_tactics

class CliTests(unittest.TestCase):
    def test_json_tactic_list_preserves_embedded_commas(self):
        tactic="rw [Nat.div_div_eq_div_mul, Nat.mul_comm]"
        self.assertEqual(parse_tactics('["'+tactic+'"]'),[tactic])
    def test_legacy_tactic_list(self): self.assertEqual(parse_tactics("rfl,trivial"),["rfl","trivial"])
