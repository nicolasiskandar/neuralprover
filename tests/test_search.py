import unittest
from neuralproof.lean.client import LeanClient,TacticCandidate
from neuralproof.models.predictor import StaticPredictor
from neuralproof.search.best_first import best_first

class SearchTests(unittest.TestCase):
    def test_toy_search_verified(self):
        r=best_first(LeanClient(timeout=15),"theorem searched : True",StaticPredictor(["exact True.intro"]),max_nodes=2,width=1)
        self.assertTrue(r.verified); self.assertEqual(r.tactic_calls,1)
    def test_node_budget(self):
        r=best_first(LeanClient(timeout=15),"theorem stuck : False",StaticPredictor(["trivial"]),max_nodes=1,width=1)
        self.assertFalse(r.verified); self.assertLessEqual(r.expanded,1)
    def test_predictor_receives_inspected_initial_goal(self):
        class CapturingPredictor:
            goals=()
            def predict(self,state,k):
                self.goals=state.goals
                return [TacticCandidate("exact True.intro",1.0)]
        predictor=CapturingPredictor()
        r=best_first(LeanClient(timeout=15),"theorem goal_is_supplied : True",predictor,max_nodes=1,width=1)
        self.assertTrue(r.verified)
        self.assertEqual(predictor.goals,("⊢ True",))
