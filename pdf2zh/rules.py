"""Preservation rules that distinguish the Code4Life PDF translation core."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

FORMULA_FONT_PATTERN = re.compile(
    r"(CM[^R]|MS.M|XY|MT|BL|RM|EU|LA|RS|LINE|LCIRCLE|TeX-|rsfs|txsy|wasy|"
    r"stmary|.*Mono|.*Code|.*Sym|.*Math|.*Typewriter|Cousine|Consolas|Menlo|"
    r"Monaco|Inconsolata|Source.?Code|Fira.?Code|DejaVu.?Sans.?Mono|"
    r"Liberation.?Mono|Courier)"
)

BULLET_CHARACTERS = frozenset(
    ("•", "■", "□", "▪", "▸", "▹", "►", "▶", "●", "○", "◆", "◇", "★", "☆", "‣", "⬤")
)

LANGUAGE_LINE_HEIGHT = {
    "zh-cn": 1.4,
    "zh-tw": 1.4,
    "zh-hans": 1.4,
    "zh-hant": 1.4,
    "zh": 1.4,
    "ja": 1.1,
    "ko": 1.2,
    "en": 1.2,
    "ar": 1.0,
    "ru": 0.8,
    "uk": 0.8,
    "ta": 0.8,
    "vi": 1.2,
}


@dataclass(frozen=True)
class PreservationDecision:
    """A page classification whose layout must remain untouched."""

    kind: str
    detail: str


def is_formula_font(font_name: str) -> bool:
    """Return whether a font name marks formula or code text."""
    return FORMULA_FONT_PATTERN.match(font_name) is not None


def line_height_for_language(language: str) -> float:
    """Return the translation line-height multiplier for a target language."""
    return LANGUAGE_LINE_HEIGHT.get(language.lower(), 1.1)


def is_scanned_page(blocks: Iterable[Mapping[str, Any]], page_area: float) -> bool:
    """Return whether a rendered image covers more than half of the page."""
    if page_area <= 0:
        return False
    for block in blocks:
        if block.get("type") != 1:
            continue
        bbox = block.get("bbox")
        if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
            continue
        x0, y0, x1, y1 = (float(value) for value in bbox)
        if max(0.0, x1 - x0) * max(0.0, y1 - y0) > page_area * 0.5:
            return True
    return False


# An index entry is a term followed by the pages it appears on, and the numbers
# are the end of the line: "metagrammar, 45, 88". An author-date citation looks
# similar - "(Miller, 1984)" - but sits inside a sentence that carries on past
# it. Matching ",<number>" anywhere read a page of ordinary academic prose as an
# index and left the whole thing untranslated.
INDEX_ENTRY_PATTERN = re.compile(
    r"^[^()]*?[A-Za-z\u00c0-\u1ef9)][^()]*?,\s*\d{1,4}(?:\s*[-–]\s*\d{1,4})?"
    r"(?:\s*,\s*\d{1,4}(?:\s*[-–]\s*\d{1,4})?)*\s*$"
)

# A bibliography entry opens with a surname and an initial or given name:
# "Halliday, M. A. K. (1978)" or "Miller, Carolyn (1984)". Prose opens with the
# surname and goes straight on - "Halliday (1978) argued that ..." - so the
# comma is what separates the two, and making it optional was what let every
# citing sentence count as a reference.
AUTHOR_YEAR_ENTRY_PATTERN = re.compile(
    r"^[A-Z][\w'’\-]+(?:\s+[A-Z][\w'’\-]+)?,\s*"
    r"(?:[A-Z]\.(?:\s*[A-Z]\.)*|[A-Z][a-z]+)"
)


def is_index_entry(line: str) -> bool:
    """Return whether a line is an index entry rather than a sentence citing a year."""
    if not INDEX_ENTRY_PATTERN.match(line):
        return False
    # "... (Miller, 1984)" ends in a number too, but inside brackets.
    return not re.search(r"[(\[][^()\[\]]*,\s*\d{1,4}[^()\[\]]*[)\]]\s*$", line)


def is_author_year_entry(line: str) -> bool:
    """Return whether a line opens a bibliography entry rather than a sentence."""
    return bool(AUTHOR_YEAR_ENTRY_PATTERN.match(line)) and bool(
        re.search(r"\(\d{4}\)|\b(19|20)\d{2}\b", line)
    )


def classify_preserved_page(page_text: str) -> PreservationDecision | None:
    """Classify pages whose number-heavy structure must not be reflowed."""
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    if not lines:
        return None

    toc_score = 0
    standalone_nums = 0
    spaced_page_nums = 0
    emspace_page_nums = 0
    for line in lines:
        if (
            re.search(r"\.{5,}", line)
            or re.search(r"(\.\s){4,}", line)
            or re.search(r"[\x08\ufffd\u2500-\u257f]{3,}", line)
        ):
            toc_score += 3
        elif re.search(r"[\x08\ufffd\u2500-\u257f]+\s*\d{1,4}\s*$", line):
            toc_score += 2
        elif re.search(r"\S\s{5,}\d{1,4}\s*$", line):
            spaced_page_nums += 1
        elif re.fullmatch(r"\d{1,4}", line):
            standalone_nums += 1

        if re.search(r"[\u2002\u2003]+\s*\d{1,4}\s*$", line) or re.search(
            r"[\u2002\u2003]+\s*[ivxlcdm]+\s*$", line, re.IGNORECASE
        ):
            emspace_page_nums += 1

    has_contents_header = any(
        re.fullmatch(r"(table\s+of\s+)?contents?", line, re.IGNORECASE)
        for line in lines[:5]
    )
    if has_contents_header:
        toc_score += 5
    if spaced_page_nums >= 5:
        toc_score += spaced_page_nums
    if emspace_page_nums >= 5:
        toc_score += emspace_page_nums
    if standalone_nums >= 8 and toc_score > 0:
        toc_score += standalone_nums
    if len(lines) >= 15 and standalone_nums >= 10 and standalone_nums / len(lines) > 0.3:
        toc_score += standalone_nums
    if len(lines) >= 15:
        lines_ending_num = sum(
            1 for line in lines if re.search(r"\S\s+\d{1,4}\s*$", line)
        )
        if lines_ending_num / len(lines) > 0.8:
            toc_score += lines_ending_num
    if toc_score >= 8:
        return PreservationDecision("TOC", f"score={toc_score}")

    index_comma_numbers = sum(1 for line in lines if is_index_entry(line))
    if len(lines) >= 20 and index_comma_numbers / len(lines) > 0.4:
        return PreservationDecision(
            "INDEX", f"comma_num={index_comma_numbers}/{len(lines)}"
        )
    if re.fullmatch(r"index", lines[0], re.IGNORECASE):
        return PreservationDecision("INDEX", "header")

    has_nomenclature_header = any(
        re.fullmatch(
            r"(nomenclature|list\s+of\s+symbols|symbols?\s+and\s+abbreviations?|"
            r"glossary|notation)s?",
            line,
            re.IGNORECASE,
        )
        for line in lines[:5]
    )
    if has_nomenclature_header and len(lines) >= 10:
        symbol_definition_pairs = sum(
            1
            for index in range(len(lines) - 1)
            if len(lines[index]) <= 15
            and len(lines[index + 1]) > 5
            and not lines[index].isdigit()
        )
        if symbol_definition_pairs / len(lines) > 0.3:
            return PreservationDecision(
                "NOMENCLATURE",
                f"pairs={symbol_definition_pairs}/{len(lines)}",
            )

    has_reference_header = any(
        re.fullmatch(
            r"[\xad]?(references?|bibliography|suggested\s+reading|further\s+reading|"
            r"works?\s+cited)",
            line,
            re.IGNORECASE,
        )
        for line in lines[:10]
    )
    numbered_refs = sum(1 for line in lines if re.match(r"^\d{1,3}\.\s", line))
    author_year_refs = sum(1 for line in lines if is_author_year_entry(line))
    bracketed_refs = sum(1 for line in lines if re.match(r"^\[\d{1,3}\]", line))
    year_parentheses = sum(1 for line in lines if re.search(r"\(\d{4}\)", line))
    isbn_doi = sum(
        1
        for line in lines
        if re.search(r"ISBN|ISSN|doi\.org|https?://", line, re.IGNORECASE)
    )
    all_refs = numbered_refs + author_year_refs + bracketed_refs
    reference_signals = all_refs + year_parentheses + isbn_doi
    if has_reference_header and reference_signals >= 5:
        return PreservationDecision(
            "REFERENCES",
            f"header, refs={all_refs}, years={year_parentheses}, isbn_doi={isbn_doi}",
        )
    if len(lines) >= 10 and all_refs >= 5 and year_parentheses + isbn_doi >= 3:
        return PreservationDecision(
            "REFERENCES",
            f"refs={all_refs}, years={year_parentheses}, isbn_doi={isbn_doi}",
        )
    return None


def is_reference_entry(line: str) -> bool:
    """Return whether a line opens a bibliography entry in any of the usual styles."""
    return bool(
        re.match(r"^\[\d{1,3}\]", line)
        or re.match(r"^\d{1,3}\.\s", line)
        or is_author_year_entry(line)
    )


PRESERVED_BLOCK_HEADER = re.compile(
    r"[\xad]?(references?|bibliography|suggested\s+reading|further\s+reading|"
    r"works?\s+cited|index|nomenclature|list\s+of\s+symbols|glossary|notation|"
    r"(table\s+of\s+)?contents?)s?",
    re.IGNORECASE,
)

FILL_CHARACTERS = r"[\x08\ufffd\u2500-\u257f]"


def is_contents_entry(line: str) -> bool:
    """Return whether a line is a contents entry: a title, then its page number."""
    return bool(
        re.search(r"\.{5,}", line)
        or re.search(r"(\.\s){4,}", line)
        or re.search(FILL_CHARACTERS + r"{3,}", line)
        or re.search(FILL_CHARACTERS + r"+\s*\d{1,4}\s*$", line)
        or re.search(r"\S\s{5,}\d{1,4}\s*$", line)
        or re.search(r"[\u2002\u2003]+\s*(\d{1,4}|[ivxlcdm]+)\s*$", line, re.IGNORECASE)
        or re.search(r"\S\s+\d{1,4}\s*$", line)
    )


# Which line test belongs to which page-level verdict. A kind that is absent
# keeps whole-page preservation: better to leave a page untranslated than to
# reflow half of a structure whose entries this cannot recognise.
BLOCK_ENTRY_TESTS = {
    "TOC": is_contents_entry,
    "INDEX": is_index_entry,
    "REFERENCES": is_reference_entry,
}


def block_is_preserved(block_text: str, is_entry) -> bool:
    """Return whether one block is a list of entries rather than prose.

    Judged by density, not by a count: a block is entries when most of its lines
    are entries. A paragraph that cites four sources is still a paragraph.
    """
    lines = [line.strip() for line in block_text.splitlines() if line.strip()]
    if not lines:
        return False
    body = [line for line in lines if not PRESERVED_BLOCK_HEADER.fullmatch(line)]
    if not body:
        # A lone "References" or "Index" heading belongs with the list under it.
        return True
    return sum(1 for line in body if is_entry(line)) / len(body) > 0.6


def preserved_regions(
    blocks: Iterable[Mapping[str, Any]], kind: str
) -> list[tuple[float, float, float, float]]:
    """Return the boxes of the blocks on a page that must not be reflowed.

    Preserving the whole page was what cost the translation: a chapter that ends
    with its reference list took the prose above it down as well. Deciding per
    block keeps the prose translatable and the list intact. An empty result
    means "no opinion" - the caller preserves the page as it used to.
    """
    is_entry = BLOCK_ENTRY_TESTS.get(kind)
    if is_entry is None:
        return []
    regions: list[tuple[float, float, float, float]] = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        bbox = block.get("bbox")
        if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
            continue
        text = "\n".join(
            "".join(span.get("text", "") for span in line.get("spans", ()))
            for line in block.get("lines", ())
        )
        if block_is_preserved(text, is_entry):
            regions.append(tuple(float(value) for value in bbox))
    return regions
