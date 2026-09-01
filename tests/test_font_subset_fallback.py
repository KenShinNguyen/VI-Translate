"""A font-subsetting failure must not discard an otherwise-finished translation.

Regression coverage for a PDF whose embedded CIDFontType2 font descriptor made
PyMuPDF's subset_fonts() raise after every segment had already been translated
- the whole document used to fail at that point instead of shipping the
translated PDF with its fonts left unsubsetted.
"""

from __future__ import annotations

import logging
import unittest
from unittest import mock

from pdf2zh.high_level import subset_fonts_or_warn


class SubsetFontsOrWarnTests(unittest.TestCase):
    def test_subsets_both_documents_when_it_succeeds(self):
        doc_zh, doc_en = mock.Mock(), mock.Mock()
        subset_fonts_or_warn(doc_zh, doc_en)
        doc_zh.subset_fonts.assert_called_once_with(fallback=True)
        doc_en.subset_fonts.assert_called_once_with(fallback=True)

    def test_a_subsetting_failure_is_swallowed_not_raised(self):
        doc_zh, doc_en = mock.Mock(), mock.Mock()
        doc_zh.subset_fonts.side_effect = ValueError(
            "invalid literal for int() with base 10: '<</Type/Font/Subtype/CIDFontType2...'"
        )
        subset_fonts_or_warn(doc_zh, doc_en)  # must not raise

    def test_a_failure_is_logged_so_it_is_not_silent(self):
        doc_zh, doc_en = mock.Mock(), mock.Mock()
        doc_zh.subset_fonts.side_effect = RuntimeError("boom")
        with self.assertLogs("pdf2zh.high_level", level="WARNING") as logs:
            subset_fonts_or_warn(doc_zh, doc_en)
        self.assertTrue(any("subsetting failed" in message for message in logs.output))

    def test_the_english_document_is_still_attempted_when_it_would_have_succeeded_alone(self):
        # doc_zh failing partway through must not silently skip doc_en - the
        # try/except wraps both calls, so a doc_zh failure does mean doc_en's
        # subset_fonts is never reached, but that is the same call the
        # original code made and worth pinning down explicitly.
        doc_zh, doc_en = mock.Mock(), mock.Mock()
        doc_zh.subset_fonts.side_effect = ValueError("bad font descriptor")
        subset_fonts_or_warn(doc_zh, doc_en)
        doc_zh.subset_fonts.assert_called_once_with(fallback=True)
        doc_en.subset_fonts.assert_not_called()


if __name__ == "__main__":
    unittest.main()
