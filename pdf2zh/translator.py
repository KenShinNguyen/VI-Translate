"""Translation adapters for the preservation-focused PDF core."""

from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import unicodedata
from concurrent.futures import Future
from typing import Any, ClassVar

import requests

from pdf2zh.cache import TranslationCache
from pdf2zh.glossary import GlossaryEntry, load_glossary, matching_terms, terminology_block

logger = logging.getLogger(__name__)

# What the converter actually substitutes for a formula or code run: see the
# "{{v{len(var)}}}" writes in converter.py. Whitespace is tolerated around the
# number because the renderer tolerates it, but the number itself is required:
# matching [\d\s]+ instead accepted "{v }", which names no formula at all.
PLACEHOLDER_PATTERN = re.compile(r"\{\s*v\s*(\d+)\s*\}")


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
        envs: dict[str, Any] | None = None,
        **_: Any,
    ) -> None:
        self.lang_in = self.lang_map.get(lang_in.lower(), lang_in)
        self.lang_out = self.lang_map.get(lang_out.lower(), lang_out)
        self.model = model
        self.ignore_cache = ignore_cache
        # One entry per call currently out to the engine, so the workers that
        # want the same text can wait on it instead of asking again. Popped on
        # completion, so this holds at most one entry per worker thread.
        self._inflight: dict[str, Future] = {}
        self._inflight_lock = threading.Lock()
        # Set by the converter before each page's worker pool, so a translator
        # that reports segments can say where one came from.
        self.current_page: int | None = None
        envs = envs or {}
        self.cache = TranslationCache(
            self.name,
            {
                "lang_in": self.lang_in,
                "lang_out": self.lang_out,
                "model": model,
            },
            domain=envs.get("domain"),
            source_document=envs.get("source_document"),
        )

    def translate(self, text: str, ignore_cache: bool = False) -> str:
        """Translate text once, however many workers ask for it at the same time.

        The cache only helps once an answer is back. Until then the workers on
        a page that repeat a string - a table label, a running head - would each
        open their own request for it, so the first caller does the work and the
        rest wait on its result.
        """
        use_cache = not (self.ignore_cache or ignore_cache)
        if use_cache:
            cached = self.cache.get(text)
            if cached is not None:
                return cached

        with self._inflight_lock:
            pending = self._inflight.get(text)
            leading = pending is None
            if leading:
                pending = self._inflight[text] = Future()

        if not leading:
            # Re-raises whatever the leading call raised, so a waiter fails the
            # same way it would have alone and the caller's retry still applies.
            return pending.result()

        try:
            translated = self.do_translate(text)
        except BaseException as error:
            pending.set_exception(error)
            raise
        else:
            # Settled before the entry goes, so a caller arriving in between
            # finds a finished future rather than starting a second request.
            pending.set_result(translated)
        finally:
            with self._inflight_lock:
                self._inflight.pop(text, None)

        if use_cache:
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

    Normalising mirrors the renderer, which reads the number out of a tag with
    int() and so treats "{ v0 }", "{v 0}" and "{v00}" as the same formula.
    Without it, a translator that merely respaced a tag would be read as having
    dropped the formula it stands for.
    """
    return [f"{{v{int(number)}}}" for number in PLACEHOLDER_PATTERN.findall(text)]


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
# Fast and inexpensive default: a book is thousands of short segments, and the
# quality gap between Claude models matters far less here than for open-ended
# generation. Override per run with "anthropic:<model>" (--engine anthropic
# --model ...) for a stronger model.
ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _anthropic_system_prompt(lang_out: str) -> str:
    """System prompt enforcing the same fidelity contract Handoff mode documents."""
    return (
        f"Translate the user's text into the language identified by the code "
        f"'{lang_out}'. Reply with the translation only - no preamble, quotation "
        "marks, or commentary. Preserve URLs, file paths, identifiers, citation "
        "markers, and numbers exactly as written. Formula and code placeholders "
        "such as {v0} or {v12} are immutable: keep every one, with the same "
        "count and order as the source, and never translate, renumber, drop, "
        "or explain them."
    )


class AnthropicTranslator(BaseTranslator):
    """Translate through the Anthropic Messages API.

    Reads its key from `ANTHROPIC_API_KEY`; the runner checks for it before
    starting a translation so a missing key fails fast instead of after the
    layout pass has already run. Unlike Google, this engine accepts a per-run
    model id through the "anthropic:<model>" service string, since Claude
    models trade off speed, cost, and translation quality differently.
    """

    name = "anthropic"

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
        super().__init__(lang_in, lang_out, model, ignore_cache=ignore_cache, envs=envs, **kwargs)
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY environment variable is required for --engine anthropic"
            )
        self.model_name = model or ANTHROPIC_DEFAULT_MODEL
        self.system_prompt = _anthropic_system_prompt(self.lang_out)
        self.glossary: dict[str, GlossaryEntry] = load_glossary((envs or {}).get("glossary"))
        self.session = requests.Session()

    def do_translate(self, text: str) -> str:
        system_prompt = self.system_prompt
        matches = matching_terms(text, self.glossary, self.lang_out)
        block = terminology_block(matches, self.lang_out)
        if block:
            system_prompt = f"{system_prompt}\n\n{block}"

        response = self.session.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": self.model_name,
                # A generous ceiling sized off the input: translated Vietnamese
                # prose runs longer than English, but a paragraph-sized segment
                # never approaches the model's real output limit.
                "max_tokens": min(8192, max(1024, len(text) // 2 + 512)),
                "system": system_prompt,
                "messages": [{"role": "user", "content": text}],
            },
            timeout=60,
        )
        if response.status_code == 401:
            raise RuntimeError("Anthropic API rejected the request: invalid ANTHROPIC_API_KEY")
        response.raise_for_status()
        payload = response.json()
        try:
            translated = "".join(
                block["text"] for block in payload["content"] if block.get("type") == "text"
            )
        except (KeyError, TypeError) as error:
            raise RuntimeError("Anthropic API response did not contain translated text") from error
        translated = remove_control_characters(translated.strip())
        if not translated:
            raise RuntimeError("Anthropic API returned an empty translation")
        if placeholders(text) != placeholders(translated):
            raise RuntimeError(
                "Anthropic API response dropped, reordered, or duplicated a formula placeholder"
            )
        return translated


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
        # The outer BaseTranslator.translate() wrapper's own cache read/write
        # must stay off regardless of ignore_cache: a miss falls through as
        # `text` unchanged, indistinguishable from a real translation to that
        # generic wrapper, so it would memoise "translation == original" for
        # every later run. do_translate() below manages its own translation-
        # memory reads and writes instead, gated on the caller's actual
        # ignore_cache request via `self._use_tm`.
        super().__init__(lang_in, lang_out, model, ignore_cache=True, envs=envs, **kwargs)
        self._use_tm = not ignore_cache
        envs = envs or {}
        self.table = load_segment_table(envs.get("segments_in"))
        self.misses_path = envs.get("segments_out")
        self.glossary: dict[str, GlossaryEntry] = load_glossary(envs.get("glossary"))
        self._seen: set[str] = set()
        self._emitted = 0
        self._lock = threading.Lock()
        if self.misses_path:
            open(self.misses_path, "w", encoding="utf-8").close()

    def do_translate(self, text: str) -> str:
        translation = self.table.get(text)
        if translation is not None:
            # A translation supplied for this run - the strongest signal
            # available, since it came from the table the caller (agent or
            # human) explicitly filled in. Worth remembering for the next
            # chapter of the same book, or the next run of this one.
            if self._use_tm:
                self.cache.set(text, translation)
            return translation
        if self._use_tm:
            remembered = self.cache.get(text)
            if remembered is not None:
                # A prior run already resolved this exact (or normalized-
                # equivalent) segment - reuse it instead of asking again.
                return remembered
        self._record_miss(text)
        return text

    def _record_miss(self, text: str) -> None:
        """Append one untranslated segment, deduplicated, for the caller to fill in.

        `src` is the only field the loader reads back; `id` and `page` are there
        to give whoever translates the file somewhere to look the segment up.
        Deliberately not an identity: two occurrences of the same text are one
        record, which is what keeps a term translated the same way throughout a
        book.

        `terms` is present only when a glossary was given and at least one of
        its terms occurs in `text`; it names the exact translation the agent
        must use for each, so a term is not left to whichever segment gets
        translated first. Omitted rather than emitted empty, so a record with
        no glossary hits reads the same as it did before this field existed.
        """
        if not self.misses_path:
            return
        with self._lock:
            if text in self._seen:
                return
            self._seen.add(text)
            self._emitted += 1
            record: dict[str, Any] = {"id": f"seg-{self._emitted:08d}"}
            if self.current_page is not None:
                record["page"] = self.current_page
            record["src"] = text
            matches = matching_terms(text, self.glossary, self.lang_out)
            if matches:
                record["terms"] = {
                    entry.term: entry.translation_for(self.lang_out) for entry in matches
                }
            with open(self.misses_path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")


ENGINES: dict[str, type[BaseTranslator]] = {
    engine.name: engine for engine in (GoogleTranslator, AnthropicTranslator, HandoffTranslator)
}
