import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neuralproof.data.info_tree_corpus import extract_info_tree_corpus


class InfoTreeCorpusTests(unittest.TestCase):
    def test_checkpoint_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "mathlib"
            source = root / "Mathlib" / "A.lean"
            source.parent.mkdir(parents=True)
            text = "import Lean\ntheorem t : True := by\n  trivial\n"
            source.write_text(text)
            start = len(text[:text.index("trivial")].encode())
            end = start + len("trivial")
            trace = {"source_file": "Mathlib/A.lean", "source_revision": "pinned", "traces": [
                {"declaration": "t", "syntax_kind": "Lean.Parser.Term.byTactic",
                 "source_start": str(start - 4), "source_end": str(end + 1),
                 "tactic": "by", "goal_state": "⊢ True", "result_state": "no goals", "completed": True},
                {"declaration": "t", "syntax_kind": "Lean.Parser.Tactic.tacticTrivial",
                 "source_start": str(start), "source_end": str(end),
                 "tactic": "trivial", "goal_state": "⊢ True", "result_state": "no goals", "completed": True},
            ]}
            output = Path(td) / "out"
            with patch("neuralproof.data.info_tree_corpus.trace_file", return_value=trace) as trace_mock:
                first = extract_info_tree_corpus(root, output, files=1)
                second = extract_info_tree_corpus(root, output, files=1)
            self.assertEqual(trace_mock.call_count, 1)
            self.assertEqual(first["examples"], 1)
            self.assertEqual(second["duplicate_example_ids"], 0)
            self.assertEqual(second["cross_split_declaration_name_overlap_pairs"], 0)
            self.assertEqual(second["split_source_files"]["train"], 1)
            row = json.loads((output / "examples.jsonl").read_text())
            self.assertEqual(row["target_tactic"], "trivial")
            self.assertEqual(row["validation"], "original_file_elaborated; transition_replay_pending")


if __name__ == "__main__":
    unittest.main()
