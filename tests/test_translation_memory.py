"""The cache is a book-scale translation memory: exact and normalized reuse,
plus provenance (domain, source document) recorded on every entry.
"""

from __future__ import annotations

import unicodedata
import unittest

from pdf2zh.cache import TranslationCache, clean_test_db, init_test_db, normalize_text


class NormalizeTextTests(unittest.TestCase):
    def test_collapses_whitespace_runs(self):
        self.assertEqual(normalize_text("Heat   flows\ndownhill"), "Heat flows downhill")

    def test_strips_leading_and_trailing_whitespace(self):
        self.assertEqual(normalize_text("  Heat flows  "), "Heat flows")

    def test_leaves_case_and_punctuation_alone(self):
        # Folding either risks treating two different source strings as the
        # same one - "Apple" the company and "apple" the fruit must not share
        # a cached translation just because they normalize identically.
        self.assertEqual(normalize_text("Apple Inc., founded in 1976."), "Apple Inc., founded in 1976.")

    def test_normalizes_unicode_form(self):
        # The same word built two ways - precomposed vs. base letter plus a
        # combining accent - renders identically but compares unequal as raw
        # strings. Built with unicodedata rather than typed literals so the
        # two forms are guaranteed to differ at the byte level.
        precomposed = unicodedata.normalize("NFC", "café")
        decomposed = unicodedata.normalize("NFD", "café")
        self.assertNotEqual(precomposed, decomposed)
        self.assertEqual(normalize_text(precomposed), normalize_text(decomposed))


class TranslationCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_db = init_test_db()

    def tearDown(self) -> None:
        clean_test_db(self.test_db)

    def _cache(self, **kwargs) -> TranslationCache:
        return TranslationCache("handoff", {"lang_in": "auto", "lang_out": "vi"}, **kwargs)

    def test_an_exact_match_is_reused(self):
        cache = self._cache()
        cache.set("Strategic warning is...", "canh bao chien luoc la...")
        self.assertEqual(cache.get("Strategic warning is..."), "canh bao chien luoc la...")

    def test_a_miss_returns_none(self):
        self.assertIsNone(self._cache().get("never seen this"))

    def test_a_whitespace_variant_reuses_the_same_entry(self):
        cache = self._cache()
        cache.set("Strategic warning is...", "canh bao chien luoc la...")
        # A later chapter re-extracted with a different line wrap.
        self.assertEqual(
            cache.get("Strategic   warning\nis..."), "canh bao chien luoc la..."
        )

    def test_a_unicode_form_variant_reuses_the_same_entry(self):
        cache = self._cache()
        precomposed = unicodedata.normalize("NFC", "café culture")
        decomposed = unicodedata.normalize("NFD", "café culture")
        cache.set(precomposed, "van hoa ca phe")
        self.assertEqual(cache.get(decomposed), "van hoa ca phe")

    def test_different_engines_do_not_share_entries(self):
        google = TranslationCache("google", {"lang_in": "auto", "lang_out": "vi"})
        anthropic = TranslationCache("anthropic", {"lang_in": "auto", "lang_out": "vi"})
        google.set("Heat flows downhill", "Nhiet chay xuong doc")
        self.assertIsNone(anthropic.get("Heat flows downhill"))

    def test_different_language_pairs_do_not_share_entries(self):
        to_vi = TranslationCache("handoff", {"lang_in": "auto", "lang_out": "vi"})
        to_fr = TranslationCache("handoff", {"lang_in": "auto", "lang_out": "fr"})
        to_vi.set("Heat flows downhill", "Nhiet chay xuong doc")
        self.assertIsNone(to_fr.get("Heat flows downhill"))

    def test_domain_and_source_document_ride_along_but_do_not_gate_lookup(self):
        # v1 scope: provenance is recorded for later inspection/QA, not yet
        # used to filter matches - a lookup from a different domain or book
        # still reuses the entry.
        writer = self._cache(domain="logic", source_document="chapter-1.pdf")
        writer.set("A premise supports a conclusion.", "Mot tien de ho tro mot ket luan.")

        reader = self._cache(domain="strategic-intelligence", source_document="chapter-9.pdf")
        self.assertEqual(
            reader.get("A premise supports a conclusion."), "Mot tien de ho tro mot ket luan."
        )

    def test_a_later_write_replaces_the_translation_for_the_same_source(self):
        cache = self._cache()
        cache.set("Heat flows downhill", "ban dich cu")
        cache.set("Heat flows downhill", "ban dich moi")
        self.assertEqual(cache.get("Heat flows downhill"), "ban dich moi")


if __name__ == "__main__":
    unittest.main()
