"""Translation adapters for the preservation-focused PDF core."""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import unicodedata
from typing import Any, ClassVar

import requests

from pdf2zh.cache import TranslationCache

logger = logging.getLogger(__name__)

# What the converter actually substitutes for a formula or code run: see the
# "{{v{len(var)}}}" writes in converter.py. The renderer that puts the formulas
# back tolerates stray whitespace inside a tag, so this has to match it.
PLACEHOLDER_PATTERN = re.compile(r"\{\s*v[\d\s]+\}")


def remove_control_characters(value: str) -> str:
    """Remove control characters that cannot be emitted safely into PDF text."""
    return "".join(character for character in value if unicodedata.category(character)[0] != "C")


class BaseTranslator:
    """Cache-aware translator interface consumed by the PDF converter."""

    name = "base"
    lang_map: ClassVar[dict[str, str]] = {}

    def __init__(
        self,
        lang_in: str,
        lang_out: str,
        model: str | None = None,
        *,
        ignore_cache: bool = False,
        **_: Any,
    ) -> None:
        self.lang_in = self.lang_map.get(lang_in.lower(), lang_in)
        self.lang_out = self.lang_map.get(lang_out.lower(), lang_out)
        self.model = model
        self.ignore_cache = ignore_cache
        self.cache = TranslationCache(
            self.name,
            {
                "lang_in": self.lang_in,
                "lang_out": self.lang_out,
                "model": model,
            },
        )

    def translate(self, text: str, ignore_cache: bool = False) -> str:
        """Translate text, consulting the persistent cache unless bypassed."""
        if not (self.ignore_cache or ignore_cache):
            cached = self.cache.get(text)
            if cached is not None:
                return cached
        translated = self.do_translate(text)
        if not (self.ignore_cache or ignore_cache):
            self.cache.set(text, translated)
        return translated

    def do_translate(self, text: str) -> str:
        """Translate one engine-sized text segment."""
        raise NotImplementedError


# Google's endpoint takes the text as a query parameter, and a longer one comes
# back rejected. Segments this long are rare - one dense paragraph in a textbook
# - but a whole page used to be a single truncated request, and the tail of it
# just vanished from the output with nothing said.
QUERY_LIMIT = 5000


def split_for_query(text: str, limit: int = QUERY_LIMIT) -> list[str]:
    """Split text into pieces of at most `limit` characters, joinable back with "".

    Splits at the last sentence end inside the limit, then the last space, so a
    piece is translated as whole sentences wherever the text allows it. A
    formula placeholder is never cut in half: the renderer matches "{vN}" as one
    token and would drop a formula whose tag arrived in two pieces.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    pieces: list[str] = []
    remainder = text
    while len(remainder) > limit:
        window = remainder[:limit]
        cut = _last_sentence_end(window) or _last_space(window) or limit
        cut = _outside_placeholder(remainder, cut)
        pieces.append(remainder[:cut])
        remainder = remainder[cut:]
    if remainder:
        pieces.append(remainder)
    return pieces


def _last_sentence_end(window: str) -> int:
    """Offset just past the last sentence-ending punctuation, or 0 if there is none."""
    return _last_end(r"[.!?;:]\s+", window)


def _last_space(window: str) -> int:
    """Offset just past the last run of whitespace, or 0 if there is none."""
    return _last_end(r"\s+", window)


def _last_end(pattern: str, window: str) -> int:
    """Offset just past the last match of `pattern` in `window`, or 0 if there is none."""
    matches = list(re.finditer(pattern, window))
    return matches[-1].end() if matches else 0


def _outside_placeholder(text: str, cut: int) -> int:
    """Move `cut` off the inside of a "{vN}" tag, preferring to keep the tag whole."""
    for match in PLACEHOLDER_PATTERN.finditer(text):
        if match.start() >= cut:
            break  # finditer is lazy, so this never scans past the cut
        if cut < match.end():
            # Before the tag if that leaves anything, otherwise after it - which
            # may exceed the limit, but a tag is far shorter than the slack the
            # endpoint allows, and losing a formula is the worse outcome.
            return match.start() or match.end()
    return cut


class GoogleTranslator(BaseTranslator):
    """Translate through Google's mobile web endpoint without an API key."""

    name = "google"
    lang_map: ClassVar[dict[str, str]] = {"zh": "zh-CN"}

    def __init__(
        self,
        lang_in: str,
        lang_out: str,
        model: str | None = None,
        *,
        ignore_cache: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            lang_in,
            lang_out,
            model,
            ignore_cache=ignore_cache,
            **kwargs,
        )
        self.session = requests.Session()
        self.endpoint = "https://translate.google.com/m"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
            )
        }

    def do_translate(self, text: str) -> str:
        """Translate one segment, splitting it up if the endpoint cannot take it whole."""
        if len(text) <= QUERY_LIMIT:
            return self._translate_one(text)
        pieces = split_for_query(text)
        rendered: list[str] = []
        for index, piece in enumerate(pieces):
            translated = self._translate_one(piece)
            # The endpoint trims the whitespace off its answer, so a split made
            # at a space would weld the last word of one piece onto the first
            # word of the next. Put the boundary back when the source had one.
            if (
                index
                and pieces[index - 1][-1:].isspace()
                and not rendered[-1].endswith(" ")
                and not translated.startswith(" ")
            ):
                rendered.append(" ")
            rendered.append(translated)
        return "".join(rendered)

    def _translate_one(self, text: str) -> str:
        response = self.session.get(
            self.endpoint,
            params={"tl": self.lang_out, "sl": self.lang_in, "q": text},
            headers=self.headers,
            timeout=30,
        )
        if response.status_code == 400:
            raise RuntimeError("Google Translate rejected the text segment")
        response.raise_for_status()
        match = re.search(
            r'(?s)class="(?:t0|result-container)">(.*?)<',
            response.text,
        )
        if match is None:
            raise RuntimeError("Google Translate response did not contain a translation result")
        return remove_control_characters(html.unescape(match.group(1)))


def placeholders(text: str) -> list[str]:
    """Return the formula placeholders in order, normalised: ['{v0}', '{v1}'].

    Normalising mirrors the renderer, which strips spaces out of a tag before
    reading its number. Without that, a translator that returned "{ v0 }" for
    "{v0}" would be read as having dropped the formula.
    """
    return [
        "{v" + "".join(character for character in match if character.isdigit()) + "}"
        for match in PLACEHOLDER_PATTERN.findall(text)
    ]


def load_segment_table(path: str | None) -> dict[str, str]:
    """Load a source-to-translation table from a JSONL file of {"src", "dst"} records.

    Entries whose translation dropped or reordered a formula placeholder are
    skipped, so the next pass re-emits them instead of silently losing a formula.
    """
    if not path:
        return {}
    table: dict[str, str] = {}
    with open(path, encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                source, translation = record["src"], record["dst"]
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError(
                    f"{path} line {number}: expected a JSON object with 'src' and 'dst'"
                ) from error
            if not isinstance(source, str) or not isinstance(translation, str):
                raise ValueError(f"{path} line {number}: 'src' and 'dst' must be strings")
            if not translation:
                continue
            if placeholders(source) != placeholders(translation):
                logger.warning(
                    "%s line %d: formula placeholders differ between src and dst; "
                    "segment left untranslated",
                    path,
                    number,
                )
                continue
            table[source] = translation
    return table


class HandoffTranslator(BaseTranslator):
    """Translate from a table produced outside the pipeline, such as by an agent.

    Two passes: the first runs with no table and records every segment it could
    not translate, the caller fills those in, and the second runs with the filled
    table to emit the real document.
    """

    name = "handoff"

    def __init__(
        self,
        lang_in: str,
        lang_out: str,
        model: str | None = None,
        *,
        ignore_cache: bool = False,
        envs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        # Misses fall through untranslated, so the shared cache must never see them
        # or "translation == original" is memoised for every later run.
        super().__init__(lang_in, lang_out, model, ignore_cache=True, **kwargs)
        envs = envs or {}
        self.table = load_segment_table(envs.get("segments_in"))
        self.misses_path = envs.get("segments_out")
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        if self.misses_path:
            open(self.misses_path, "w", encoding="utf-8").close()

    def do_translate(self, text: str) -> str:
        translation = self.table.get(text)
        if translation is not None:
            return translation
        self._record_miss(text)
        return text

    def _record_miss(self, text: str) -> None:
        """Append one untranslated segment, deduplicated, for the caller to fill in."""
        if not self.misses_path:
            return
        with self._lock:
            if text in self._seen:
                return
            self._seen.add(text)
            with open(self.misses_path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps({"src": text}, ensure_ascii=False) + "\n")


ENGINES: dict[str, type[BaseTranslator]] = {
    engine.name: engine for engine in (GoogleTranslator, HandoffTranslator)
}
