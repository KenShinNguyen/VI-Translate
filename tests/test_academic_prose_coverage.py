"""Academic prose must be translated, however densely it cites its sources.

Both preservation rules had a line test that ordinary prose satisfies. A page
that cited enough sources was classified as a reference list or an index, and
preservation threw the entire page away untranslated - which is most of a
humanities book, where author-date citation is simply how sentences are written.
"""

from __future__ import annotations

import unittest

from pdf2zh.rules import (
    block_is_preserved,
    classify_preserved_page,
    is_author_year_entry,
    is_contents_entry,
    is_index_entry,
    is_reference_entry,
    preserved_regions,
)

CITING_PROSE_LINES = [
    "Halliday (1978) argued that language is a social semiotic, and that",
    "grammar encodes a speaker's construal of experience. Later work by",
    "Martin (1992) extended this into genre theory, where a genre is a",
    "staged, goal-oriented social process. Bazerman (1988) showed how the",
    "experimental article emerged as a genre over three centuries, and",
    "Miller (1984) reframed genre as social action rather than form.",
    "Swales (1990) then introduced the notion of discourse community.",
    "Bakhtin (1981) insisted every utterance answers prior utterances.",
    "Freadman (2002) called this uptake, a term that has since spread.",
    "Devitt (2004) later complicated the discourse-community notion.",
    "Notation matters here: abduction is inference to the best explanation,",
    "and metaduction extends that move upward into the metagrammar itself.",
]

AUTHOR_DATE_PROSE_LINES = [
    "the notion of genre (Miller, 1984) has been productive here, and",
    "subsequent work (Bazerman, 1988) refined it considerably further",
] * 11

REFERENCE_LINES = [
    "References",
    "Bakhtin, M. M. (1981) The Dialogic Imagination. Austin: Texas UP.",
    "Bazerman, C. (1988) Shaping Written Knowledge. Madison: Wisconsin UP.",
    "Devitt, A. J. (2004) Writing Genres. Carbondale: Southern Illinois UP.",
    "Halliday, M. A. K. (1978) Language as Social Semiotic. London: Arnold.",
    "Martin, J. R. (1992) English Text. Amsterdam: Benjamins.",
    "Miller, C. R. (1984) Genre as social action. QJS 70, 151-167.",
    "Swales, J. (1990) Genre Analysis. Cambridge: Cambridge UP.",
    "ISBN 978-0-521-33813-4",
]

INDEX_LINES = [
    "Index",
    "abduction, 88, 142",
    "agency, 33-40, 91",
    "discourse community, 61",
    "genre, 12, 88, 140-155",
    "grammar, 3, 7, 19",
    "metaduction, 143",
    "metagrammar, 45, 88",
    "notation, 102",
    "representation, 7, 19, 204",
    "social semiotic, 22",
    "uptake, 133",
]


def _block(lines):
    """A pymupdf text block carrying these lines."""
    return {
        "type": 0,
        "bbox": (60.0, 80.0, 540.0, 400.0),
        "lines": [{"spans": [{"text": line}]} for line in lines],
    }


class LineTests(unittest.TestCase):
    def test_a_citing_sentence_is_not_a_bibliography_entry(self):
        for line in CITING_PROSE_LINES:
            with self.subTest(line=line[:40]):
                self.assertFalse(is_author_year_entry(line))
                self.assertFalse(is_reference_entry(line))

    def test_a_real_bibliography_entry_still_is_one(self):
        for line in REFERENCE_LINES[1:-1]:
            with self.subTest(line=line[:40]):
                self.assertTrue(is_reference_entry(line))

    def test_an_author_date_citation_is_not_an_index_entry(self):
        for line in AUTHOR_DATE_PROSE_LINES[:2]:
            with self.subTest(line=line[:40]):
                self.assertFalse(is_index_entry(line))

    def test_a_real_index_entry_still_is_one(self):
        for line in INDEX_LINES[1:]:
            with self.subTest(line=line[:40]):
                self.assertTrue(is_index_entry(line))

    def test_a_contents_entry_is_recognised_in_its_usual_shapes(self):
        for line in (
            "Chapter 1 Introduction . . . . . . . . 1",
            "Introduction.........................12",
            "Preface ix",
            "Heat transfer     88",
        ):
            with self.subTest(line=line):
                self.assertTrue(is_contents_entry(line))


class PageTests(unittest.TestCase):
    def test_prose_that_cites_sources_is_not_a_reference_page(self):
        self.assertIsNone(classify_preserved_page("\n".join(CITING_PROSE_LINES)))

    def test_author_date_prose_is_not_an_index_page(self):
        self.assertIsNone(classify_preserved_page("\n".join(AUTHOR_DATE_PROSE_LINES)))

    def test_one_more_citation_no_longer_flips_a_prose_page(self):
        # The old threshold sat one ordinary sentence away from throwing the
        # whole page out, so this pair used to straddle it.
        extra = "Bawarshi (2003) pushed the argument further still."
        self.assertIsNone(classify_preserved_page("\n".join(CITING_PROSE_LINES)))
        self.assertIsNone(
            classify_preserved_page("\n".join([*CITING_PROSE_LINES, extra]))
        )

    def test_a_real_reference_page_is_still_preserved(self):
        self.assertIsNotNone(classify_preserved_page("\n".join(REFERENCE_LINES)))

    def test_a_real_index_page_is_still_preserved(self):
        self.assertIsNotNone(classify_preserved_page("\n".join(INDEX_LINES)))


class RegionTests(unittest.TestCase):
    def test_only_the_reference_block_of_a_mixed_page_is_preserved(self):
        blocks = [_block(CITING_PROSE_LINES), _block(REFERENCE_LINES)]
        regions = preserved_regions(blocks, "REFERENCES")
        self.assertEqual(len(regions), 1, "the prose block must stay translatable")

    def test_a_prose_block_is_never_preserved(self):
        self.assertFalse(block_is_preserved("\n".join(CITING_PROSE_LINES), is_reference_entry))
        self.assertFalse(
            block_is_preserved("\n".join(AUTHOR_DATE_PROSE_LINES), is_index_entry)
        )

    def test_a_kind_with_no_block_test_defers_to_the_whole_page(self):
        # NOMENCLATURE entries are symbol/definition pairs this cannot judge per
        # block, so it says nothing and the caller preserves the page as before.
        self.assertEqual(preserved_regions([_block(INDEX_LINES)], "NOMENCLATURE"), [])

    def test_a_lone_heading_block_travels_with_its_list(self):
        self.assertTrue(block_is_preserved("References", is_reference_entry))


if __name__ == "__main__":
    unittest.main()
