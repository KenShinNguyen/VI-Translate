from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from app.gui import LANGUAGE_NAMES, collect_pdfs
except ImportError:  # customtkinter and tkinterdnd2 are app-only dependencies
    collect_pdfs = None

from scripts.translate_pdf import TARGET_LANGUAGES


@unittest.skipIf(collect_pdfs is None, "desktop app dependencies are not installed")
class CollectPdfsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)
        for name in ("b.pdf", "a.pdf", "UPPER.PDF"):
            (self.root / name).write_bytes(b"%PDF-1.7\n")
        (self.root / "notes.txt").write_text("not a pdf", encoding="utf-8")
        (self.root / "folder.pdf").mkdir()
        nested = self.root / "sub"
        nested.mkdir()
        (nested / "deep.pdf").write_bytes(b"%PDF-1.7\n")

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_a_directory_expands_to_its_pdfs_without_recursing(self):
        names = [path.name for path in collect_pdfs([self.root])]
        self.assertEqual(names, ["a.pdf", "b.pdf", "UPPER.PDF"])

    def test_a_directory_named_like_a_pdf_is_not_queued(self):
        self.assertNotIn("folder.pdf", [path.name for path in collect_pdfs([self.root])])

    def test_non_pdf_files_are_dropped(self):
        self.assertEqual(collect_pdfs([self.root / "notes.txt"]), [])

    def test_duplicates_collapse_across_a_directory_and_an_explicit_file(self):
        result = collect_pdfs([self.root, self.root / "a.pdf"])
        self.assertEqual(len(result), 3)
        self.assertEqual(len(set(result)), 3)

    def test_a_vanished_file_stays_queued_so_the_runner_can_report_it(self):
        names = [path.name for path in collect_pdfs([self.root / "gone.pdf"])]
        self.assertEqual(names, ["gone.pdf"])


@unittest.skipIf(collect_pdfs is None, "desktop app dependencies are not installed")
class LanguageMenuTests(unittest.TestCase):
    def test_every_supported_language_has_a_menu_label(self):
        self.assertEqual(set(LANGUAGE_NAMES), set(TARGET_LANGUAGES))

    def test_menu_labels_are_unique_so_the_reverse_lookup_is_total(self):
        self.assertEqual(len(set(LANGUAGE_NAMES.values())), len(LANGUAGE_NAMES))


if __name__ == "__main__":
    unittest.main()
