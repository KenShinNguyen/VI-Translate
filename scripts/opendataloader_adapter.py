#!/usr/bin/env python3
"""Convert OpenDataLoader-PDF JSON into VI-Translate handoff segments.

The adapter deliberately accepts the common OpenDataLoader JSON shapes instead of
coupling the translation pipeline to one parser version. It preserves page,
bounding-box and semantic-type metadata in an optional sidecar while emitting the
minimal {id,page,src} JSONL contract consumed by the handoff engine.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

TEXT_KEYS = ("text", "content", "value", "markdown")
TYPE_KEYS = ("type", "element_type", "semantic_type")
PAGE_KEYS = ("page", "page_number", "page number")
BOX_KEYS = ("bounding box", "bounding_box", "bbox", "coordinates")
SKIP_TYPES = {"image", "figure", "chart", "header", "footer", "watermark"}
TRANSLATABLE_TYPES = {
    "paragraph", "text", "heading", "title", "list", "list_item", "caption",
    "footnote", "quote", "table_cell", "table", "abstract", "section"
}


def _first(d: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in d and d[key] not in (None, ""):
            return d[key]
    return None


def _page(value: Any, inherited: int | None = None) -> int | None:
    if isinstance(value, bool):
        return inherited
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return inherited


def _walk(node: Any, page: int | None = None) -> Iterable[tuple[dict[str, Any], int | None]]:
    if isinstance(node, dict):
        current_page = _page(_first(node, PAGE_KEYS), page)
        yield node, current_page
        for value in node.values():
            yield from _walk(value, current_page)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, page)


def _clean(text: str) -> str:
    text = text.replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def _is_translatable(record: dict[str, Any], text: str) -> bool:
    kind = str(_first(record, TYPE_KEYS) or "paragraph").lower().replace("-", "_")
    if kind in SKIP_TYPES:
        return False
    if kind in TRANSLATABLE_TYPES:
        return True
    # Unknown element types are accepted when they carry substantial text.
    return len(text) >= 2


def extract_segments(data: Any) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str]] = set()
    for record, page in _walk(data):
        raw = _first(record, TEXT_KEYS)
        if not isinstance(raw, str):
            continue
        text = _clean(raw)
        if not text or not _is_translatable(record, text):
            continue
        key = (page, text)
        if key in seen:
            continue
        seen.add(key)
        kind = str(_first(record, TYPE_KEYS) or "paragraph").lower().replace("-", "_")
        segments.append({
            "id": f"seg-{len(segments) + 1:08d}",
            "page": page,
            "type": kind,
            "bbox": _first(record, BOX_KEYS),
            "src": text,
        })
    return segments


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenDataLoader JSON -> VI-Translate handoff JSONL")
    parser.add_argument("input_json", type=Path)
    parser.add_argument("output_jsonl", type=Path)
    parser.add_argument("--metadata", type=Path, help="Optional sidecar JSON retaining page/type/bbox metadata")
    args = parser.parse_args()

    data = json.loads(args.input_json.read_text(encoding="utf-8"))
    segments = extract_segments(data)
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with args.output_jsonl.open("w", encoding="utf-8", newline="\n") as handle:
        for segment in segments:
            handle.write(json.dumps({"id": segment["id"], "page": segment["page"], "src": segment["src"]}, ensure_ascii=False) + "\n")
    if args.metadata:
        args.metadata.parent.mkdir(parents=True, exist_ok=True)
        args.metadata.write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Created {len(segments)} translation segments: {args.output_jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
