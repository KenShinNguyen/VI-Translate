"""Which font the engine draws the translation in must not depend on the machine.

It used to read C:/Windows/Fonts/times.ttf for Vietnamese, so the same document
came out in a serif on one machine, in whatever the fallback was on another, and
the packaged app's own bundled font was bypassed on Windows entirely.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from pdf2zh import high_level


class BundledSerifTests(unittest.TestCase):
    def test_the_serif_and_its_licence_ship_with_the_repository(self):
        serif = high_level.BUNDLED_FONT_DIRECTORY / high_level.LATIN_SERIF_NAME
        self.assertTrue(serif.is_file(), f"{serif} is missing")
        licences = list(high_level.BUNDLED_FONT_DIRECTORY.glob("LiberationSerif-*OFL*"))
        self.assertTrue(licences, "the OFL text has to travel with the font")

    def test_every_supported_target_language_gets_the_bundled_serif(self):
        from scripts.translate_pdf import TARGET_LANGUAGES

        serif = (high_level.BUNDLED_FONT_DIRECTORY / high_level.LATIN_SERIF_NAME).as_posix()
        for language in sorted(TARGET_LANGUAGES):
            with self.subTest(language=language):
                self.assertEqual(high_level.download_remote_fonts(language), serif)

    def test_the_choice_never_reaches_for_a_windows_path(self):
        # Code only: the comment above the lookup names the old path on purpose,
        # and rewording it must not fail this.
        code = [
            line.split("#", 1)[0]
            for line in Path(high_level.__file__).read_text(encoding="utf-8").splitlines()
        ]
        offenders = [line.strip() for line in code if "C:/" in line or "C:\\" in line]
        self.assertEqual(offenders, [])

    def test_a_script_the_serif_does_not_cover_still_uses_noto(self):
        # Cyrillic, Thai and the CJK targets are not what this serif is for, so
        # they must keep going through babeldoc's font list.
        with mock.patch.object(
            high_level, "get_font_and_metadata", return_value=(Path("/noto.ttf"), None)
        ) as fetch:
            for language in ("ru", "th", "ja", "zh"):
                with self.subTest(language=language):
                    self.assertEqual(high_level.download_remote_fonts(language), "/noto.ttf")
        self.assertEqual(fetch.call_count, 4)

    def test_a_build_that_points_somewhere_else_is_still_obeyed(self):
        # NOTO_FONT_PATH is how the packaged build points at what it ships.
        with mock.patch.dict("os.environ", {"NOTO_FONT_PATH": __file__}):
            self.assertEqual(high_level.download_remote_fonts("ru"), __file__)


if __name__ == "__main__":
    unittest.main()
