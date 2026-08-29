"""translate_patch must keep deciding page preservation through pdf2zh.rules.

The classification used to be spelled out a second time inside translate_patch,
so a fix applied to rules.py silently did nothing to the pipeline. These tests
run the real page loop over a real PDF - with the layout model stubbed out, so
they need neither the 70 MB ONNX download nor a network - and assert on the
`layout` mask the loop hands to the converter.
"""

from __future__ import annotations

import io
import unittest
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

CONTENTS = (
    "Contents\n\n"
    "Chapter 1 Introduction . . . . . . . . 1\n"
    "Chapter 2 Conduction . . . . . . . . 17\n"
    "Chapter 3 Convection . . . . . . . . 42\n"
    "Chapter 4 Radiation . . . . . . . . . 78\n"
    "Chapter 5 Boiling . . . . . . . . . . 96\n"
    "Chapter 6 Exchangers . . . . . . . 120\n"
)


class _EmptyPrediction:
    """A layout model that finds nothing, so only the text rules move the mask."""

    boxes: list = []
    names: dict = {}


class _StubModel:
    def predict(self, image, imgsz=1024):
        return [_EmptyPrediction()]


@unittest.skipIf(pymupdf is None, "pymupdf is not installed")
class TranslatePatchPreservationTests(unittest.TestCase):
    @staticmethod
    def _document(*pages: str) -> bytes:
        document = pymupdf.open()
        for text in pages:
            page = document.new_page()
            page.insert_textbox(
                pymupdf.Rect(60, 80, 540, 400), text, fontsize=11, fontname="helv"
            )
        return document.tobytes()

    def _layout_for(self, *pages: str) -> dict:
        """Run the real page loop and return the mask it built for each page."""
        data = self._document(*pages)
        captured: dict = {}
        real_converter = high_level.TranslateConverter

        def capture(rsrcmgr, vfont, vchar, thread, layout, *args, **kwargs):
            captured["layout"] = layout
            return real_converter(rsrcmgr, vfont, vchar, thread, layout, *args, **kwargs)

        with mock.patch.object(high_level, "TranslateConverter", capture):
            high_level.translate_patch(
                io.BytesIO(data),
                doc_zh=pymupdf.open(stream=data),
                model=_StubModel(),
                service="handoff",
                envs={},
                lang_in="auto",
                lang_out="vi",
                noto_name="helv",
                noto=pymupdf.Font("helv"),
                thread=1,
            )
        return captured["layout"]

    def test_a_contents_page_is_preserved_and_prose_is_not(self):
        layout = self._layout_for(PROSE, CONTENTS)
        self.assertTrue(layout[0].any(), "prose page should stay translatable")
        self.assertFalse(layout[1].any(), "contents page should be preserved")

    def test_the_decision_comes_from_the_rules_module(self):
        # Re-inlining the heuristics would make this pass while rules.py is dead.
        with mock.patch.object(
            high_level, "classify_preserved_page", return_value=None
        ) as classify:
            layout = self._layout_for(PROSE, CONTENTS)
        self.assertEqual(classify.call_count, 2)
        self.assertTrue(layout[1].any(), "no rule fired, so nothing may be preserved")


if __name__ == "__main__":
    unittest.main()
