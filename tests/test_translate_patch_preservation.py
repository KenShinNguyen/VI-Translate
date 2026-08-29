"""What the real page loop does, over a real PDF, with the layout model stubbed.

Stubbing the model means these need neither the 70 MB ONNX download nor a
network. They assert on what a reader would actually see: which text comes back
as a segment to translate, and which is left in the source language on purpose.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import pymupdf
except ImportError:  # pragma: no cover - pymupdf is a core dependency
    pymupdf = None

if pymupdf is not None:
    from pdf2zh import high_level

PROSE = (
    "Conduction occurs when two bodies are in direct contact with each other. "
    "The rate of heat transfer depends on the thermal conductivity of the "
    "material and on the temperature gradient across it. This paragraph gives "
    "the layout pass a real block of prose to reflow into the target language."
)

OTHER_PROSE = (
    "Convection carries heat with a moving fluid across the boundary layer. "
    "It dominates wherever the fluid is free to circulate, which is why a fan "
    "changes the answer so much more than a thicker wall does."
)

CONTENTS = (
    "Contents\n\n"
    "Chapter 1 Introduction . . . . . . . . 1\n"
    "Chapter 2 Conduction . . . . . . . . 17\n"
    "Chapter 3 Convection . . . . . . . . 42\n"
    "Chapter 4 Radiation . . . . . . . . . 78\n"
    "Chapter 5 Boiling . . . . . . . . . . 96\n"
    "Chapter 6 Exchangers . . . . . . . 120\n"
)

# Prose that cites sources the way an academic book does. Every line of this
# used to be thrown away: the citations tripped the reference and index rules,
# and preservation took the whole page.
CITING_PROSE = (
    "Halliday (1978) argued that language is a social semiotic, and that "
    "grammar encodes a speaker's construal of experience. Martin (1992) "
    "extended this into genre theory. Bazerman (1988) showed how the "
    "experimental article emerged as a genre. Miller (1984) reframed genre "
    "as social action rather than form, and the notion of genre (Swales, 1990) "
    "has been productive ever since. Bakhtin (1981) insisted that every "
    "utterance answers prior utterances, a point Freadman (2002) called uptake."
)

REFERENCE_LIST = (
    "References\n\n"
    "Bakhtin, M. M. (1981) The Dialogic Imagination. Austin: Texas UP.\n"
    "Bazerman, C. (1988) Shaping Written Knowledge. Madison: Wisconsin UP.\n"
    "Halliday, M. A. K. (1978) Language as Social Semiotic. London: Arnold.\n"
    "Martin, J. R. (1992) English Text. Amsterdam: Benjamins.\n"
    "Miller, C. R. (1984) Genre as social action. QJS 70, 151-167.\n"
    "Swales, J. (1990) Genre Analysis. Cambridge: Cambridge UP.\n"
)


class _EmptyPrediction:
    """A layout model that finds nothing, so only the text rules move the mask."""

    boxes: list = []
    names: dict = {}


class _StubModel:
    def predict(self, image, imgsz=1024):
        return [_EmptyPrediction()]


@unittest.skipIf(pymupdf is None, "pymupdf is not installed")
class PageLoopTests(unittest.TestCase):
    @staticmethod
    def _document(*pages: tuple[str, ...]) -> bytes:
        """One page per argument; a tuple of strings becomes stacked blocks."""
        document = pymupdf.open()
        for page_content in pages:
            page = document.new_page()
            blocks = (
                (page_content,) if isinstance(page_content, str) else page_content
            )
            top = 80
            for text in blocks:
                page.insert_textbox(
                    pymupdf.Rect(60, top, 540, top + 300),
                    text,
                    fontsize=11,
                    fontname="helv",
                )
                top += 320
        return document.tobytes()

    def _run(self, *pages) -> tuple[dict, list[dict]]:
        """Run the real page loop; return the layout masks and reported segments."""
        data = self._document(*pages)
        captured: dict = {}
        real_converter = high_level.TranslateConverter

        def capture(rsrcmgr, vfont, vchar, thread, layout, *args, **kwargs):
            captured["layout"] = layout
            return real_converter(rsrcmgr, vfont, vchar, thread, layout, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            misses = Path(directory) / "segments.jsonl"
            with mock.patch.object(high_level, "TranslateConverter", capture):
                high_level.translate_patch(
                    io.BytesIO(data),
                    doc_zh=pymupdf.open(stream=data),
                    model=_StubModel(),
                    service="handoff",
                    envs={"segments_out": str(misses)},
                    lang_in="auto",
                    lang_out="vi",
                    noto_name="helv",
                    noto=pymupdf.Font("helv"),
                    thread=1,
                )
            records = [
                json.loads(line)
                for line in misses.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        return captured["layout"], records

    @staticmethod
    def _text_of(records, page: int) -> str:
        return " ".join(r["src"] for r in records if r.get("page") == page)

    def test_a_contents_page_is_preserved_and_prose_is_not(self):
        layout, records = self._run(PROSE, CONTENTS)
        self.assertTrue(layout[0].any(), "prose page should stay translatable")
        self.assertIn("Conduction", self._text_of(records, 1))
        self.assertEqual(self._text_of(records, 2), "", "contents must be preserved")

    def test_the_decision_comes_from_the_rules_module(self):
        # Re-inlining the heuristics would make this pass while rules.py is dead.
        with mock.patch.object(
            high_level, "classify_preserved_page", return_value=None
        ) as classify:
            _, records = self._run(PROSE, CONTENTS)
        self.assertEqual(classify.call_count, 2)
        self.assertIn("Chapter", self._text_of(records, 2))

    def test_prose_that_cites_sources_is_still_translated(self):
        # The regression the whole rule tightening exists for.
        _, records = self._run(CITING_PROSE)
        self.assertIn("Halliday", self._text_of(records, 1))

    def test_a_reference_list_is_preserved_without_taking_the_prose_with_it(self):
        # A chapter that ends with its bibliography: the prose above it must
        # still be translated, which whole-page preservation made impossible.
        _, records = self._run((CITING_PROSE, REFERENCE_LIST))
        reported = self._text_of(records, 1)
        self.assertIn("Halliday (1978) argued", reported)
        self.assertNotIn("Amsterdam: Benjamins", reported)

    def test_each_segment_is_reported_against_the_page_it_came_from(self):
        _, records = self._run(PROSE, OTHER_PROSE)
        self.assertEqual([record["page"] for record in records], [1, 2])
        self.assertTrue(all(record["id"] for record in records))
        self.assertIn("Conduction", records[0]["src"])
        self.assertIn("Convection", records[1]["src"])


if __name__ == "__main__":
    unittest.main()
