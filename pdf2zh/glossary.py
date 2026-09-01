"""A persistent, locked term glossary the translation engines are told to
follow, instead of leaving word choice to whichever segment reaches the
engine first.

v1 scope is deliberately narrow: one glossary file per run, applied to the
whole document (there is no per-chapter or per-section layering yet), and
`domain` is carried through for the reader's own organisation rather than
filtered against anything. An engine asks `matching_terms` for the entries
that actually occur in one segment, so a large glossary does not inflate
every prompt with terms the segment never uses.

This module does not verify that an engine's output actually used the
mandated translation - that belongs to a QA pass run after translation, not
to the translator that only gets to ask once per segment.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# Keys on a glossary entry that are not a target-language translation. Every
# other key is read as "translation for this language code".
_ENTRY_METADATA_KEYS = frozenset({"domain", "locked"})


@dataclass(frozen=True)
class GlossaryEntry:
    """One glossary term, with its mandated translation per target language."""

    term: str
    translations: dict[str, str]
    domain: str | None = None
    locked: bool = True

    def translation_for(self, lang_out: str) -> str | None:
        return self.translations.get(lang_out.lower())


def load_glossary(path: str | Path | None) -> dict[str, GlossaryEntry]:
    """Load a term glossary from a JSON file.

    Format: `{"term": {"<lang>": "translation", ..., "domain": "...", "locked": true}}`.
    A missing `path` (None or "") loads an empty glossary, so callers can
    treat "no glossary given" and "glossary with no entries" the same way.
    """
    if not path:
        return {}
    source = Path(path)
    try:
        with source.open(encoding="utf-8") as stream:
            raw = json.load(stream)
    except json.JSONDecodeError as error:
        raise ValueError(f"{source}: not valid JSON ({error})") from error

    if not isinstance(raw, dict):
        raise ValueError(f"{source}: glossary must be a JSON object of term -> entry")

    glossary: dict[str, GlossaryEntry] = {}
    for term, value in raw.items():
        if not isinstance(term, str) or not term.strip():
            raise ValueError(f"{source}: glossary term keys must be non-empty strings")
        if not isinstance(value, dict):
            raise ValueError(f"{source}: entry for {term!r} must be a JSON object")

        translations = {
            lang.lower(): translation
            for lang, translation in value.items()
            if lang not in _ENTRY_METADATA_KEYS
        }
        if not translations:
            raise ValueError(
                f"{source}: entry for {term!r} has no target-language translation"
            )
        for lang, translation in translations.items():
            if not isinstance(translation, str) or not translation:
                raise ValueError(
                    f"{source}: entry for {term!r} has an empty translation for {lang!r}"
                )

        domain = value.get("domain")
        if domain is not None and not isinstance(domain, str):
            raise ValueError(f"{source}: 'domain' for {term!r} must be a string")

        glossary[term] = GlossaryEntry(
            term=term,
            translations=translations,
            domain=domain,
            locked=bool(value.get("locked", True)),
        )
    return glossary


def matching_terms(
    text: str, glossary: dict[str, GlossaryEntry], lang_out: str
) -> list[GlossaryEntry]:
    """Glossary entries whose term occurs whole-word in `text`, in glossary order.

    Skips an entry with no translation for `lang_out`: a physics glossary
    loaded for a French target should not surface a Vietnamese-only entry.
    """
    matches: list[GlossaryEntry] = []
    for entry in glossary.values():
        if entry.translation_for(lang_out) is None:
            continue
        if re.search(rf"\b{re.escape(entry.term)}\b", text, re.IGNORECASE):
            matches.append(entry)
    return matches


def terminology_block(matches: list[GlossaryEntry], lang_out: str) -> str:
    """Render matched entries as the "MANDATORY TERMINOLOGY" prompt block, or "" for none."""
    if not matches:
        return ""
    lines = "\n".join(f"{entry.term} = {entry.translation_for(lang_out)}" for entry in matches)
    return f"MANDATORY TERMINOLOGY\n\n{lines}"
