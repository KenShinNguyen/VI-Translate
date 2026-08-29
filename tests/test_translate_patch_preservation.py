"""What the real page loop does, over a real PDF, with the layout model stubbed.

Stubbing the model means these need neither the 70 MB ONNX download nor a
network. They cover two things unit tests cannot reach: the preservation
decision the loop hands to the converter as a `layout` mask - which used to be
spelled out a second time inside translate_patch, so a fix applied to rules.py
silently did nothing - and the page number the converter puts on the translator
for the segments it reports.
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


@unittest.skipIf(pymupdf is None, "pymupdf is not installed")
class ReportedSegmentContextTests(unittest.TestCase):
    """The page a reported segment came from has to survive the worker pool."""

    def _emit(self, *pages: str, threads: int = 2) -> list[dict]:
        document = pymupdf.open()
        for text in pages:
            page = document.new_page()
            page.insert_textbox(
                pymupdf.Rect(60, 80, 540, 400), text, fontsize=11, fontname="helv"
            )
        data = document.tobytes()

        with tempfile.TemporaryDirectory() as directory:
            misses = Path(directory) / "segments.jsonl"
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
                thread=threads,
            )
            return [
                json.loads(line)
                for line in misses.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

    def test_each_segment_is_reported_against_the_page_it_came_from(self):
        records = self._emit(PROSE, OTHER_PROSE)
        self.assertEqual([record["page"] for record in records], [1, 2])
        # One-based, so it lines up with the page numbers the loop logs.
        self.assertTrue(all(record["id"] for record in records))
        self.assertIn("Conduction", records[0]["src"])
        self.assertIn("Convection", records[1]["src"])
