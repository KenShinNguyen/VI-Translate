#!/usr/bin/env python3
"""Expert PDF translation pipeline using OpenDataLoader + VI-Translate.

Pipeline:
  PDF -> OpenDataLoader JSON/Markdown -> structured segments -> terminology-aware
  handoff translation -> VI-Translate PDF reconstruction.

OpenDataLoader is intentionally invoked as an external CLI so its Java/Python
runtime remains isolated from the bundled pdf2zh core in this repository.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ADAPTER = HERE / "opendataloader_adapter.py"
TRANSLATOR = HERE / "translate_pdf.py"


def run(cmd: list[str]) -> None:
    print("+", subprocess.list2cmdline(cmd))
    subprocess.run(cmd, check=True)


def find_odl() -> str:
    candidate = shutil.which("opendataloader-pdf")
    if candidate:
        return candidate
    raise RuntimeError(
        "OpenDataLoader CLI was not found. Install opendataloader-pdf and ensure "
        "the command is on PATH, or pass --odl-command."
    )


def load_glossary(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "terms" in data and isinstance(data["terms"], dict):
        data = data["terms"]
    if not isinstance(data, dict):
        raise ValueError("Glossary must be a JSON object or {\"terms\": {...}}")
    return {str(k): str(v) for k, v in data.items()}


def write_prompt(path: Path, glossary: dict[str, str], domain: str) -> None:
    lines = [
        "EXPERT TRANSLATION CONTRACT",
        f"Domain: {domain}",
        "Translate English to Vietnamese.",
        "Preserve meaning, logical relations, certainty, numbers, citations, URLs, identifiers, and placeholders exactly.",
        "Do not translate or modify placeholders such as {v0}, {v1}.",
        "Use the preferred terminology below consistently; do not substitute synonyms when a term is locked.",
        "",
        "PREFERRED TERMINOLOGY:",
    ]
    lines.extend(f"{src} -> {dst}" for src, dst in glossary.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Expert PDF translation: OpenDataLoader -> VI-Translate handoff")
    p.add_argument("input_pdf", type=Path)
    p.add_argument("--output-dir", type=Path, default=Path("translated"))
    p.add_argument("--work-dir", type=Path, default=Path(".translation-work"))
    p.add_argument("--domain", default="general")
    p.add_argument("--glossary", type=Path)
    p.add_argument("--odl-command", default=None, help="OpenDataLoader executable; defaults to opendataloader-pdf")
    p.add_argument("--pages", help="Optional one-based pages/ranges for VI-Translate handoff")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()

    source = args.input_pdf.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise SystemExit(f"Input PDF does not exist or is not a PDF: {source}")

    work = args.work_dir.expanduser().resolve()
    extract = work / "extraction"
    extract.mkdir(parents=True, exist_ok=True)
    segments = work / "segments.jsonl"
    metadata = work / "segments.metadata.json"
    prompt = work / "translation-contract.txt"
    translations = work / "translations.jsonl"
    missing = work / "still-missing.jsonl"
    args.output_dir.expanduser().resolve().mkdir(parents=True, exist_ok=True)

    odl = args.odl_command or find_odl()
    run([odl, str(source), "-f", "markdown,json", "-o", str(extract)])

    json_files = sorted(extract.rglob("*.json"))
    if not json_files:
        raise RuntimeError(f"OpenDataLoader produced no JSON in {extract}")
    if len(json_files) > 1:
        # Prefer a file matching the source stem; otherwise use the largest JSON.
        matching = [f for f in json_files if f.stem.lower() == source.stem.lower()]
        input_json = matching[0] if matching else max(json_files, key=lambda f: f.stat().st_size)
    else:
        input_json = json_files[0]

    run([sys.executable, str(ADAPTER), str(input_json), str(segments), "--metadata", str(metadata)])
    glossary = load_glossary(args.glossary)
    write_prompt(prompt, glossary, args.domain)

    cmd = [sys.executable, str(TRANSLATOR), str(source), "--engine", "handoff", "--emit-segments", str(missing)]
    if args.pages:
        cmd += ["--pages", args.pages]
    cmd += ["--threads", str(args.threads)]
    run(cmd)

    print("\nHandoff segments are ready:")
    print(f"  {segments}")
    print(f"Translation contract: {prompt}")
    print("\nTranslate each JSONL record into a corresponding {\"src\",\"dst\"} record.")
    print("Then rebuild with:")
    rebuild = [sys.executable, str(TRANSLATOR), str(source), "--engine", "handoff", "--segments", str(translations), "--output-dir", str(args.output_dir), "--emit-segments", str(missing)]
    if args.overwrite:
        rebuild.append("--overwrite")
    print(subprocess.list2cmdline(rebuild))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
