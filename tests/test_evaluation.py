import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from neuralproof.evaluation.metrics import summarize
from neuralproof.evaluation.tactic_prediction import evaluate_tactic_prediction
from neuralproof.lean.client import TacticCandidate
class MetricTests(unittest.TestCase):
    def test_counts(self): self.assertEqual(summarize([{"verified":True},{"verified":False}])["verified"],1)
    def test_unmeasured_tokens_are_not_zero(self): self.assertIsNone(summarize([{"verified":False,"inference_tokens":None}])["inference_tokens"])
    def test_tactic_prediction_uses_same_deterministic_single_line_test_sample(self):
        class FakePredictor:
            def __init__(self, tactic): self.tactic=tactic
            def predict(self, state, k): return [TacticCandidate(self.tactic)]
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"test.jsonl"
            rows=[{"example_id":"a","split":"test","source_file":"A.lean","context":"import Lean","goal_state":"⊢ True","target_tactic":"trivial"},
                  {"example_id":"b","split":"test","source_file":"B.lean","context":"import Lean","goal_state":"⊢ True","target_tactic":"exact\nTrue.intro"},
                  {"example_id":"c","split":"train","source_file":"C.lean","context":"import Lean","goal_state":"⊢ True","target_tactic":"trivial"}]
            source.write_text("".join(json.dumps(x)+"\n" for x in rows))
            with patch("neuralproof.models.predictor.load_hf_predictor", side_effect=[FakePredictor("trivial"),FakePredictor("rfl")]):
                result=evaluate_tactic_prediction(source,Path(td)/"result.json",base_model="base",revision="rev",adapter="lora",limit=10)
            self.assertEqual(result["heldout_examples"],2)
            self.assertEqual(result["eligible_single_line_examples"],1)
            self.assertEqual(result["base"]["exact_matches"],1)
            self.assertEqual(result["lora"]["attempted"],1)
            self.assertAlmostEqual(result["base"]["wilson95"][0],0.2065433)
            self.assertEqual(result["base"]["wilson95"][1],1.0)
