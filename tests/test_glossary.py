from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pdf2zh.glossary import load_glossary, matching_terms, terminology_block


def _write(root: Path, data: dict) -> Path:
    path = root / "glossary.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class LoadGlossaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_a_missing_path_yields_an_empty_glossary(self):
        self.assertEqual(load_glossary(None), {})
        self.assertEqual(load_glossary(""), {})

    def test_loads_terms_with_domain_and_lock_metadata(self):
        path = _write(
            self.root,
            {
                "conduction": {"vi": "dẫn nhiệt", "domain": "heat-transfer", "locked": True},
                "premise": {"vi": "tiền đề", "domain": "logic"},
            },
        )
        glossary = load_glossary(path)
        self.assertEqual(glossary["conduction"].translations, {"vi": "dẫn nhiệt"})
        self.assertEqual(glossary["conduction"].domain, "heat-transfer")
        self.assertTrue(glossary["conduction"].locked)
        # "locked" defaults to True when absent: a glossary entry is mandatory
        # unless the author explicitly says otherwise.
        self.assertTrue(glossary["premise"].locked)

    def test_locked_can_be_set_false(self):
        path = _write(self.root, {"strategic warning": {"vi": "cảnh báo chiến lược", "locked": False}})
        glossary = load_glossary(path)
        self.assertFalse(glossary["strategic warning"].locked)

    def test_an_entry_may_carry_more_than_one_target_language(self):
        path = _write(self.root, {"conduction": {"vi": "dẫn nhiệt", "fr": "conduction"}})
        entry = load_glossary(path)["conduction"]
        self.assertEqual(entry.translation_for("vi"), "dẫn nhiệt")
        self.assertEqual(entry.translation_for("FR"), "conduction")
        self.assertIsNone(entry.translation_for("de"))

    def test_rejects_malformed_json(self):
        path = self.root / "glossary.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            load_glossary(path)

    def test_rejects_a_top_level_list(self):
        path = self.root / "glossary.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must be a JSON object"):
            load_glossary(path)

    def test_rejects_an_entry_with_no_translation(self):
        path = _write(self.root, {"conduction": {"domain": "heat-transfer"}})
        with self.assertRaisesRegex(ValueError, "no target-language translation"):
            load_glossary(path)

    def test_rejects_an_empty_translation(self):
        path = _write(self.root, {"conduction": {"vi": ""}})
        with self.assertRaisesRegex(ValueError, "empty translation"):
            load_glossary(path)

    def test_rejects_a_non_object_entry(self):
        path = _write(self.root, {"conduction": "dẫn nhiệt"})
        with self.assertRaisesRegex(ValueError, "must be a JSON object"):
            load_glossary(path)


class MatchingTermsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def _glossary(self) -> dict:
        return load_glossary(
            _write(
                self.root,
                {
                    "conduction": {"vi": "dẫn nhiệt", "domain": "heat-transfer"},
                    "premise": {"vi": "tiền đề", "domain": "logic"},
                },
            )
        )

    def test_matches_a_whole_word_case_insensitively(self):
        glossary = self._glossary()
        matches = matching_terms("Conduction occurs between two bodies.", glossary, "vi")
        self.assertEqual([m.term for m in matches], ["conduction"])

    def test_does_not_match_inside_a_longer_word(self):
        glossary = self._glossary()
        matches = matching_terms("superconduction is different", glossary, "vi")
        self.assertEqual(matches, [])

    def test_returns_every_term_the_text_contains(self):
        glossary = self._glossary()
        matches = matching_terms(
            "The premise supports conduction as an example.", glossary, "vi"
        )
        self.assertEqual({m.term for m in matches}, {"conduction", "premise"})

    def test_a_term_with_no_translation_for_the_target_language_is_skipped(self):
        glossary = self._glossary()
        matches = matching_terms("Conduction occurs.", glossary, "fr")
        self.assertEqual(matches, [])

    def test_terminology_block_is_empty_for_no_matches(self):
        self.assertEqual(terminology_block([], "vi"), "")

    def test_terminology_block_lists_term_equals_translation(self):
        glossary = self._glossary()
        matches = matching_terms("The premise and conduction both matter.", glossary, "vi")
        block = terminology_block(matches, "vi")
        self.assertTrue(block.startswith("MANDATORY TERMINOLOGY"))
        self.assertIn("premise = tiền đề", block)
        self.assertIn("conduction = dẫn nhiệt", block)


if __name__ == "__main__":
    unittest.main()
