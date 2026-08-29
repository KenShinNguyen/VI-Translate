"""A segment longer than the endpoint's query limit must survive whole.

The endpoint used to be handed text[:5000], so the tail of a long paragraph
disappeared from the translated PDF with nothing logged.
"""

from __future__ import annotations

import unittest
from unittest import mock

from pdf2zh.cache import clean_test_db, init_test_db
from pdf2zh.translator import (
    QUERY_LIMIT,
    GoogleTranslator,
    placeholders,
    split_for_query,
)


class SplitForQueryTests(unittest.TestCase):
    def test_short_text_is_one_piece(self):
        self.assertEqual(split_for_query("Heat flows.", 5000), ["Heat flows."])

    def test_empty_text_yields_no_pieces(self):
        self.assertEqual(split_for_query("", 5000), [])

    def test_pieces_rejoin_into_the_original(self):
        for text in (
            "Conduction occurs. " * 900,
            "word " * 4000,
            "x" * 12000,
            "A sentence; another one: and a third! Plus a question? " * 300,
        ):
            with self.subTest(text=text[:20]):
                pieces = split_for_query(text, 500)
                self.assertEqual("".join(pieces), text)

    def test_every_piece_fits_the_limit(self):
        pieces = split_for_query("Conduction occurs here. " * 900, 500)
        self.assertTrue(pieces)
        for piece in pieces:
            self.assertLessEqual(len(piece), 500)

    def test_text_with_no_break_is_still_split(self):
        # No sentence end and no space: the split has to fall back to the limit
        # rather than loop forever or return one oversized piece.
        pieces = split_for_query("x" * 2500, 1000)
        self.assertEqual([len(piece) for piece in pieces], [1000, 1000, 500])

    def test_a_split_prefers_a_sentence_boundary(self):
        text = "First sentence here. " + "a" * 40 + " tail"
        pieces = split_for_query(text, 30)
        self.assertEqual(pieces[0], "First sentence here. ")

    def test_a_formula_placeholder_is_never_cut_in_half(self):
        # A tag split across two requests comes back as two fragments, and the
        # renderer drops the formula it stood for.
        for limit in range(8, 60):
            text = "alpha " * 4 + "{v12}" + " beta" * 20
            with self.subTest(limit=limit):
                pieces = split_for_query(text, limit)
                self.assertEqual("".join(pieces), text)
                self.assertEqual(
                    sum(len(placeholders(piece)) for piece in pieces),
                    len(placeholders(text)),
                )

    def test_a_leading_placeholder_still_makes_progress(self):
        text = "{v0}" + "y" * 40
        pieces = split_for_query(text, 3)
        self.assertEqual("".join(pieces), text)
        self.assertEqual(placeholders(pieces[0]), ["{v0}"])

    def test_a_non_positive_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            split_for_query("text", 0)


class GoogleTranslatorSplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_db = init_test_db()

    def tearDown(self) -> None:
        clean_test_db(self.test_db)

    def _translator(self) -> GoogleTranslator:
        return GoogleTranslator("auto", "vi", ignore_cache=True)

    def test_a_short_segment_is_one_request(self):
        translator = self._translator()
        with mock.patch.object(
            translator, "_translate_one", return_value="dịch"
        ) as one:
            self.assertEqual(translator.do_translate("short"), "dịch")
        one.assert_called_once_with("short")

    def test_a_long_segment_is_split_and_nothing_is_dropped(self):
        translator = self._translator()
        text = "Conduction occurs between two bodies in contact. " * 400
        self.assertGreater(len(text), QUERY_LIMIT)
        with mock.patch.object(
            translator, "_translate_one", side_effect=lambda part: part
        ) as one:
            result = translator.do_translate(text)
        self.assertGreater(one.call_count, 1)
        for call in one.call_args_list:
            self.assertLessEqual(len(call.args[0]), QUERY_LIMIT)
        self.assertEqual(result, text)

    def test_a_boundary_the_endpoint_trimmed_gets_its_space_back(self):
        translator = self._translator()
        text = "Word. " * 2000
        with mock.patch.object(
            translator, "_translate_one", side_effect=lambda part: part.strip()
        ):
            result = translator.do_translate(text)
        self.assertNotIn("Word.Word.", result)


if __name__ == "__main__":
    unittest.main()
