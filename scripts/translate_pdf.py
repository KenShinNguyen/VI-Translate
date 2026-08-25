#!/usr/bin/env python3
"""Translate one text-based PDF while preserving its layout and formulas."""

from __future__ import annotations

import argparse
import importlib
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_CORE = (SKILL_ROOT / "pdf2zh").resolve()
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

CORE_VERSION = "1.9.11"
RULESET = "code4life-preservation-v1"
DEFAULT_TARGET_LANGUAGE = "vi"

# Latin-script targets the bundled GoNotoKurrent font renders correctly. Scripts
# needing CJK glyphs, right-to-left runs, or complex shaping are refused rather
# than emitted as blank boxes or reordered text.
TARGET_LANGUAGES = frozenset(
    {
        "af", "ca", "cs", "cy", "da", "de", "en", "es", "et", "eu", "fi", "fr",
        "ga", "gl", "hr", "hu", "id", "is", "it", "lt", "lv", "ms", "mt", "nl",
        "no", "pl", "pt", "ro", "sk", "sl", "sq", "sv", "sw", "tl", "tr", "vi",
    }
)

ENGINES = ("google", "handoff")


class TranslationError(RuntimeError):
    """Raised when input validation or the translation engine fails."""


def _positive_threads(value: str) -> int:
    threads = int(value)
    if not 1 <= threads <= 4:
        raise argparse.ArgumentTypeError("threads must be between 1 and 4")
    return threads


def _page_selection(value: str) -> str:
    if not re.fullmatch(r"[1-9]\d*(?:-[1-9]\d*)?(?:,[1-9]\d*(?:-[1-9]\d*)?)*", value):
        raise argparse.ArgumentTypeError("pages must use one-based ranges such as 1,3-5")
    for item in value.split(","):
        if "-" in item:
            start, end = (int(part) for part in item.split("-", 1))
            if start > end:
                raise argparse.ArgumentTypeError("page range start must not exceed its end")
    return value


def _source_language(value: str) -> str:
    if value == "auto" or re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?", value):
        return value
    raise argparse.ArgumentTypeError("source language must be 'auto' or a Google language code")


def _target_language(value: str) -> str:
    language = value.lower()
    if language not in TARGET_LANGUAGES:
        supported = ", ".join(sorted(TARGET_LANGUAGES))
        raise argparse.ArgumentTypeError(
            f"unsupported target language {value!r}. The bundled font covers Latin-script "
            f"targets only, so CJK, right-to-left, and complex-shaping scripts would render "
            f"as blank boxes or reordered text. Supported: {supported}"
        )
    return language


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Translate one text-based PDF while preserving layout and formulas."
    )
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--target-language", default=DEFAULT_TARGET_LANGUAGE, type=_target_language
    )
    parser.add_argument("--source-language", default="auto", type=_source_language)
    parser.add_argument("--pages", type=_page_selection)
    parser.add_argument("--threads", default=2, type=_positive_threads)
    parser.add_argument("--engine", default="google", choices=ENGINES)
    parser.add_argument(
        "--segments",
        type=Path,
        help='handoff engine: JSONL of {"src","dst"} records to translate from',
    )
    parser.add_argument(
        "--emit-segments",
        type=Path,
        help="handoff engine: write the segments left untranslated here, as JSONL",
    )
    parser.add_argument("--ignore-cache", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _validate_arguments(args: argparse.Namespace) -> None:
    if args.output_dir is None and args.emit_segments is None:
        raise TranslationError("--output-dir is required unless --emit-segments is given")
    if args.engine == "handoff":
        if args.segments is None and args.emit_segments is None:
            raise TranslationError("--engine handoff needs --segments, --emit-segments, or both")
    elif args.segments is not None or args.emit_segments is not None:
        raise TranslationError("--segments and --emit-segments require --engine handoff")


def _require_core() -> None:
    try:
        import pdf2zh
        importlib.import_module("pdf2zh.doclayout")
    except ImportError as error:
        requirements = SKILL_ROOT / "requirements.txt"
        install = f'"{sys.executable}" -m pip install -r "{requirements}"'
        raise TranslationError(f"PDF core dependencies are missing. Run: {install}") from error
    if pdf2zh.__version__ != CORE_VERSION:
        raise TranslationError(
            f"Expected bundled PDF core {CORE_VERSION}, found {pdf2zh.__version__}"
        )
    if getattr(pdf2zh, "__ruleset__", None) != RULESET:
        raise TranslationError("Bundled PDF core does not expose the required preservation ruleset")
    # A packaged build has no pip environment for a PyPI wheel to shadow the core,
    # and its module paths point inside the extraction directory rather than here.
    if getattr(sys, "frozen", False):
        return
    module_path = Path(pdf2zh.__file__).resolve()
    if not module_path.is_relative_to(BUNDLED_CORE):
        raise TranslationError(f"Refusing external PDF core: {module_path}")


def _validate_input(path: Path) -> Path:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise TranslationError(f"Input PDF does not exist: {source}")
    if source.suffix.lower() != ".pdf":
        raise TranslationError(f"Input must have a .pdf extension: {source}")
    with source.open("rb") as stream:
        if b"%PDF-" not in stream.read(1024):
            raise TranslationError(f"Input does not contain a PDF header: {source}")
    return source


def _pages_to_indices(pages: str | None) -> list[int] | None:
    if pages is None:
        return None
    indices: list[int] = []
    for item in pages.split(","):
        if "-" in item:
            start, end = (int(part) for part in item.split("-", 1))
            indices.extend(range(start - 1, end))
        else:
            indices.append(int(item) - 1)
    return indices


def _segment_envs(segments: Path | None, emit_segments: Path | None) -> dict[str, str]:
    """Resolve the handoff file paths that the translator reads through `envs`."""
    envs: dict[str, str] = {}
    if segments is not None:
        source = segments.expanduser().resolve()
        if not source.is_file():
            raise TranslationError(f"Segments file does not exist: {source}")
        envs["segments_in"] = str(source)
    if emit_segments is not None:
        emitted = emit_segments.expanduser().resolve()
        emitted.parent.mkdir(parents=True, exist_ok=True)
        envs["segments_out"] = str(emitted)
    return envs


def _run_engine(
    source: Path,
    temp_output: Path,
    target_language: str,
    source_language: str,
    pages: str | None,
    threads: int,
    ignore_cache: bool,
    engine: str,
    envs: dict[str, str],
) -> None:
    from pdf2zh.doclayout import OnnxModel
    from pdf2zh.high_level import translate

    # A packaged build ships the layout model so the first run needs no network.
    bundled_model = os.environ.get("PDF_TRANSLATE_MODEL")
    model = OnnxModel(bundled_model) if bundled_model else OnnxModel.load_available()
    result = translate(
        files=[str(source)],
        output=str(temp_output),
        pages=_pages_to_indices(pages),
        lang_in=source_language,
        lang_out=target_language,
        service=engine,
        thread=threads,
        model=model,
        envs=envs,
        ignore_cache=ignore_cache,
    )
    if len(result) != 1:
        raise TranslationError("PDF core did not report one translated result")


def translate_pdf(
    input_pdf: Path,
    output_dir: Path | None,
    *,
    target_language: str = DEFAULT_TARGET_LANGUAGE,
    source_language: str = "auto",
    pages: str | None = None,
    threads: int = 2,
    ignore_cache: bool = False,
    overwrite: bool = False,
    engine: str = "google",
    segments: Path | None = None,
    emit_segments: Path | None = None,
) -> Path | None:
    """Translate one PDF. Returns the output path, or None when only emitting segments."""
    _require_core()
    source = _validate_input(input_pdf)
    envs = _segment_envs(segments, emit_segments)

    destination: Path | None = None
    destination_dir: Path | None = None
    if output_dir is not None:
        destination_dir = output_dir.expanduser().resolve()
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{source.stem}-{target_language}.pdf"
        if destination.exists() and not overwrite:
            raise TranslationError(
                f"Output already exists: {destination}. "
                "Pass --overwrite only with replacement authorization."
            )

    with tempfile.TemporaryDirectory(prefix="pdf-translate-", dir=destination_dir) as temp:
        temp_output = Path(temp)
        try:
            _run_engine(
                source,
                temp_output,
                target_language,
                source_language,
                pages,
                threads,
                ignore_cache,
                engine,
                envs,
            )
        except TranslationError:
            raise
        except Exception as error:
            raise TranslationError(f"PDF translation core failed: {error}") from error

        if destination is None:
            return None

        generated = temp_output / f"{source.stem}-mono.pdf"
        if not generated.is_file():
            candidates = sorted(temp_output.glob("*-mono.pdf"))
            if len(candidates) != 1:
                names = ", ".join(path.name for path in temp_output.iterdir()) or "no files"
                raise TranslationError(f"Engine did not produce one translated PDF; found: {names}")
            generated = candidates[0]

        staged = destination_dir / f".{destination.name}.tmp"
        try:
            shutil.copyfile(generated, staged)
            staged.replace(destination)
        finally:
            staged.unlink(missing_ok=True)

    return destination


def _use_utf8_output() -> None:
    """Print Vietnamese paths on a legacy console codepage instead of crashing.

    Windows terminals still default to cp1252, which cannot encode Vietnamese, so
    a path like D:\\Tai lieu\\sach-vi.pdf would raise after the work was done.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    _use_utf8_output()
    args = _parser().parse_args(argv)
    try:
        _validate_arguments(args)
        destination = translate_pdf(
            args.input_pdf,
            args.output_dir,
            target_language=args.target_language,
            source_language=args.source_language,
            pages=args.pages,
            threads=args.threads,
            ignore_cache=args.ignore_cache,
            overwrite=args.overwrite,
            engine=args.engine,
            segments=args.segments,
            emit_segments=args.emit_segments,
        )
    except TranslationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if destination is not None:
        print(f"Translated PDF: {destination}")
    if args.emit_segments is not None:
        emitted = args.emit_segments.expanduser().resolve()
        pending = sum(1 for line in emitted.open(encoding="utf-8") if line.strip())
        print(f"Segments left untranslated: {pending} -> {emitted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
