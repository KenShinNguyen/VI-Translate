#!/usr/bin/env python3
"""Merge VI-Translate handoff segments with OpenDataLoader metadata.

VI-Translate remains authoritative for rebuild matching: its `src` is copied
verbatim. OpenDataLoader contributes page/type/bbox metadata and nearby context.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip().casefold()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("vi_segments", type=Path)
    p.add_argument("odl_metadata", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()

    vi = [json.loads(line) for line in args.vi_segments.read_text(encoding="utf-8").splitlines() if line.strip()]
    metadata = json.loads(args.odl_metadata.read_text(encoding="utf-8"))
    odl = metadata.get("segments", metadata if isinstance(metadata, list) else [])

    exact: dict[tuple[int | None, str], dict[str, Any]] = {}
    loose: dict[str, list[dict[str, Any]]] = {}
    for item in odl:
        key = (item.get("page"), norm(str(item.get("src", ""))))
        exact[key] = item
        loose.setdefault(norm(str(item.get("src", ""))), []).append(item)

    enriched = []
    for item in vi:
        src = str(item.get("src", ""))
        page = item.get("page")
        match = exact.get((page, norm(src)))
        if match is None:
            candidates = loose.get(norm(src), [])
            match = candidates[0] if candidates else {}
        out = dict(item)
        if match:
            for key in ("type", "bbox"):
                if match.get(key) is not None:
                    out[key] = match[key]
        enriched.append(out)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in enriched) + "\n", encoding="utf-8")
    print(f"Enriched {len(enriched)} VI-Translate segments: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
