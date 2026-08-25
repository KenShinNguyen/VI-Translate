---
name: pdf-translate
description: Translate text-based PDFs into Vietnamese or another Latin-script language while preserving document layout, formulas, tables, and figures. Offers a fast Google Translate mode and an advanced mode where the agent translates the extracted segments itself. Use for PDF translation requests; do not use when OCR is required, or when the target language uses a CJK, right-to-left, or complex-shaping script.
---

# PDF Translate

Translate a local, text-based PDF into a new PDF that keeps the original layout, formulas, tables, and figures. Two modes share one engine and one preservation contract:

| Mode | Translated by | Cost | Use when |
| --- | --- | --- | --- |
| **Google** (default) | `translate.google.com` | Free, no tokens | Whole books, bulk batches, first drafts |
| **Handoff** (advanced) | You, in this conversation | Tokens and wall-clock time | Documents where terminology and context matter |

Default to Google mode. Offer handoff mode when the user asks for higher quality, complains about the Google output, or the document is short and technical.

## Boundaries

- The bundled `pdf2zh/` core owns the preservation behavior. Never install or invoke the PyPI `pdf2zh` wheel as the translation engine; doing so bypasses the Code4Life rules.
- **Google mode sends the extracted document text over the network to Google.** Tell the user before processing sensitive material, and require explicit confirmation when the request did not already authorize that disclosure. Handoff mode sends nothing to Google.
- Target languages are limited to Latin-script codes. The bundled font has no CJK glyphs, and the layout engine writes left-to-right without complex shaping, so Chinese, Japanese, Korean, Arabic, Hebrew, Thai, and Devanagari are refused rather than emitted as blank boxes or reordered text.
- The runner does not perform OCR. If the source contains only scanned page images, report that OCR is required instead of claiming the unchanged images were translated.
- The layout engine can preserve source-language text inside detected tables or figures instead of translating it. Compare source and output text, and report affected content as partial translation rather than hiding the limitation.
- Preserve the source PDF. Write the translated file to a separate output directory and do not overwrite an existing result unless the user explicitly requests replacement.

Read [the preservation contract](references/preservation-rules.md) when reviewing layout behavior, changing the core, or diagnosing an untranslated region.

## Setup

Use Python 3.11 or 3.12. Keep runtime packages isolated in `.venv` under this skill directory and install the pinned dependencies from `requirements.txt` when the environment is missing or stale. The first translation downloads layout and font assets, so it needs extra network access and takes longer than later runs.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On POSIX systems use `.venv/bin/python` instead.

Shared options: `--target-language` (default `vi`), `--source-language auto`, one-based `--pages 1,3-5`, `--threads 1..4`, `--ignore-cache`, `--overwrite`. Use `--overwrite` only with explicit replacement authorization.

## Mode 1 - Google (default)

One command per file. For a batch, loop and report progress per file rather than running them all silently.

```powershell
.venv\Scripts\python.exe scripts\translate_pdf.py INPUT.pdf --output-dir OUTPUT_DIR
```

A failure on one file must not stop the batch: record it, continue, and list every failure at the end.

## Mode 2 - Handoff (advanced)

You translate the segments yourself. The engine extracts them, you fill them in, the engine rebuilds the PDF. Nothing is sent to Google.

**Warn about cost before starting.** A 300-page book is thousands of segments. Suggest `--pages 1-5` first so the user can judge quality on a sample.

**Step 1 - extract.** No `--output-dir` is needed; the pass-one PDF is discarded.

```powershell
.venv\Scripts\python.exe scripts\translate_pdf.py INPUT.pdf --engine handoff --emit-segments segments.jsonl
```

**Step 2 - translate.** `segments.jsonl` holds one `{"src": "..."}` record per line. Read it in batches of roughly 150 records and write `translations.jsonl` with one `{"src": "...", "dst": "..."}` record per line, where `src` is copied **byte for byte** from the input.

**Formula placeholders are the one thing that must not change.** Segments contain tags like `<b0></b0>` standing in for formulas, code, and inline math. Every `<bN>` and `</bN>` tag must survive translation with the **same count, same identifiers, and same order**. A segment whose placeholders do not match its source is rejected at load time and left untranslated, so the formula would silently vanish from the output.

Also keep URLs, file paths, identifiers, citation markers, and numbers unchanged.

**Step 3 - rebuild.** Emitting misses again turns this into a loop.

```powershell
.venv\Scripts\python.exe scripts\translate_pdf.py INPUT.pdf --engine handoff `
  --segments translations.jsonl --output-dir OUTPUT_DIR --emit-segments still-missing.jsonl
```

**Step 4 - close the loop.** The command prints how many segments are still untranslated. If that count is not zero, translate `still-missing.jsonl`, append the results to `translations.jsonl`, and run step 3 again. Repeat until the count reaches zero, or tell the user which segments you could not translate and why.

Note that step 1 runs the full layout pass a second time, so a handoff translation takes roughly twice the local compute of a Google run.

## Verify

Before delivery, for either mode:

1. Reopen the output and confirm its page count matches the source.
2. Extract text from the source and output, scan every page for substantial untranslated passages, and confirm formulas, URLs, and identifiers remain recognizable.
3. Render every output page to PNG and inspect for clipped text, overlaps, missing glyphs, blank pages, or displaced figures and tables.
4. If any page fails visual inspection, keep the source and failed output, report the affected pages, and do not present the translation as complete.
