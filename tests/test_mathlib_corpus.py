import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neuralproof.data.corpus import extract_corpus


class CorpusTests(unittest.TestCase):
    def test_checkpoint_resume_and_file_split(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "mathlib"
            output = Path(temp) / "out"
            (root / "Mathlib" / "A").mkdir(parents=True)
            (root / "Mathlib" / "A" / "One.lean").write_text("-- one")
            (root / "Mathlib" / "A" / "Two.lean").write_text("-- two")
            row = {"source_file": "Mathlib/A/One.lean", "source_declaration": "A.one",
                   "goal_state": "⊢ True", "target_tactic": "trivial", "context": "import A", "split": "wrong"}

            class DummyClient:
                pass

            calls = []

            def extract(_client, _root, relative, limit):
                calls.append(relative)
                return ([dict(row)] if relative.endswith("One.lean") else [],
                        {"source_file": relative, "failures": []})

            with patch("neuralproof.data.corpus.LeanClient", DummyClient), \
                 patch("neuralproof.data.corpus.extract_mathlib_file", extract):
                first = extract_corpus(root, output, files=2, per_file=1)
                second = extract_corpus(root, output, files=2, per_file=1)
                with self.assertRaisesRegex(ValueError, "per_file_example_cap"):
                    extract_corpus(root, output, files=2, per_file=2)

            self.assertEqual(calls, ["Mathlib/A/One.lean", "Mathlib/A/Two.lean"])
            self.assertEqual(first["examples"], 1)
            self.assertEqual(second["examples"], 1)
            self.assertEqual(second["duplicate_source_declaration_ids"], 0)
            self.assertEqual(second["broad_import_context_rows"], 0)
            saved = json.loads((output / "examples.jsonl").read_text())
            self.assertIn(saved["split"], {"train", "validation", "test"})
            self.assertEqual(len((output / "file_stats.jsonl").read_text().splitlines()), 2)

    def test_resume_rejects_changed_file_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "mathlib"
            output = Path(temp) / "out"
            (root / "Mathlib").mkdir(parents=True)
            (root / "Mathlib" / "One.lean").write_text("-- one")
            with patch("neuralproof.data.corpus.LeanClient"):
                extract_corpus(root, output, files=1, per_file=1)
                (root / "Mathlib" / "Two.lean").write_text("-- two")
                with self.assertRaisesRegex(ValueError, "file_list_sha256"):
                    extract_corpus(root, output, files=2, per_file=1)


if __name__ == "__main__":
    unittest.main()
