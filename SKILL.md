---
name: pdf-translate
description: Translate local, text-based PDFs into Vietnamese or another supported Latin-script language while preserving the original layout, formulas, tables, and figures. Use for PDF translation, batch translation, terminology-sensitive handoff translation, or diagnosing incomplete translated output. Do not use for image-only scans that need OCR or targets requiring CJK, right-to-left, or complex-script shaping.
license: AGPL-3.0-only
---

# PDF Translate

Translate a PDF with the bundled Code4Life engine. Keep the source file unchanged and produce a separate PDF with the same page structure.

## Resolve the skill root

This skill may be installed globally while the user's files live elsewhere. Resolve the absolute directory containing this `SKILL.md` before running anything. Call its scripts and dependency files by absolute path; do not assume the current working directory is the skill directory.

Use the interpreter inside `<skill-root>/.venv`:

- Windows: `<skill-root>\.venv\Scripts\python.exe`
- macOS/Linux: `<skill-root>/.venv/bin/python`

## Choose a mode

| Mode | Translator | Use when |
| --- | --- | --- |
| Google (default) | `translate.google.com` | Books, batches, first drafts, or low token use |
| Anthropic | Claude API (`ANTHROPIC_API_KEY`) | Better quality than Google without occupying the active agent, and an API key is available |
| Handoff | The active agent | Terminology, context, or translation quality matters and no separate API key is available |

Default to Google. Offer Anthropic when an `ANTHROPIC_API_KEY` is available and quality matters but the document is too large to hand off to the active agent's own context. Offer handoff when the user asks for higher quality, rejects the Google result, or provides a short technical document.

## Boundaries

- Use the bundled `pdf2zh/` core. Never substitute the PyPI `pdf2zh` package; the runner checks version `1.9.11` and preservation ruleset `code4life-preservation-v1` and refuses an external core.
- Google and Anthropic mode send extracted document text to that provider. Tell the user before processing sensitive material and obtain explicit confirmation unless their request already authorizes that disclosure. Handoff mode does not contact either.
- Anthropic mode needs `ANTHROPIC_API_KEY` in the environment; the runner refuses to start without it rather than running partway and leaving segments untranslated. Pass a model with `--model` (default: a fast, low-cost Claude model) when the user wants a specific one.
- Supported targets are the Latin-script codes enforced by `scripts/translate_pdf.py`. CJK, right-to-left, Thai, Devanagari, and other complex-shaping targets are rejected because the bundled font and layout engine cannot render them reliably.
- There is no OCR. If a source page is image-only, report that OCR is required instead of claiming it was translated.
- Text inside detected tables, figures, contents pages, indexes, symbol lists, or references may intentionally remain in the source language. Report material untranslated regions as partial translation.
- Preserve the source. Write results to a separate output directory. Do not pass `--overwrite` without explicit replacement authorization.

Read [the preservation contract](references/preservation-rules.md) before changing layout behavior, diagnosing preserved pages, or investigating untranslated regions.

## Set up the runtime

Use Python 3.11 or 3.12. Create `<skill-root>/.venv` and install `<skill-root>/requirements.txt` if the environment is absent or stale. Keep this environment separate from the user's project.

The source distribution downloads layout and font assets on its first translation, so the first run needs network access and takes longer. The packaged Windows app already contains these assets.

Windows:

```powershell
python -m venv "<skill-root>\.venv"
& "<skill-root>\.venv\Scripts\python.exe" -m pip install -r "<skill-root>\requirements.txt"
```

macOS/Linux:

```bash
python3 -m venv "<skill-root>/.venv"
"<skill-root>/.venv/bin/python" -m pip install -r "<skill-root>/requirements.txt"
```

Shared runner options include `--target-language` (default `vi`), `--source-language auto`, one-based `--pages 1,3-5`, `--threads 1..8` (default `4`), `--ignore-cache`, and `--overwrite`.

## Google mode

Run one command per file. Use absolute paths for the input and output directory.

Windows:

```powershell
& "<skill-root>\.venv\Scripts\python.exe" "<skill-root>\scripts\translate_pdf.py" "<input.pdf>" --output-dir "<output-dir>"
```

macOS/Linux:

```bash
"<skill-root>/.venv/bin/python" "<skill-root>/scripts/translate_pdf.py" "<input.pdf>" --output-dir "<output-dir>"
```

For a batch, process files individually and report progress. A failure on one file must not stop the remaining files; collect and report all failures at the end.

## Anthropic mode

Requires `ANTHROPIC_API_KEY` in the environment. Same one-command-per-file shape as Google mode, plus `--engine anthropic` and an optional `--model`.

Windows:

```powershell
& "<skill-root>\.venv\Scripts\python.exe" "<skill-root>\scripts\translate_pdf.py" "<input.pdf>" --engine anthropic --output-dir "<output-dir>"
```

macOS/Linux:

```bash
"<skill-root>/.venv/bin/python" "<skill-root>/scripts/translate_pdf.py" "<input.pdf>" --engine anthropic --output-dir "<output-dir>"
```

## Handoff mode

Handoff extracts translatable segments to JSONL, lets the active agent translate them, then rebuilds the PDF. Warn about token and time cost before starting a large document. For long documents, suggest a representative sample such as `--pages 1-5` first.

### 1. Extract

An output directory is not required during extraction because the pass-one PDF is discarded.

```text
<python> <skill-root>/scripts/translate_pdf.py <input.pdf> --engine handoff --emit-segments <segments.jsonl>
```

### 2. Translate

`segments.jsonl` holds one record per segment:

```json
{"id":"seg-00000001","page":12,"src":"exact source text"}
```

`page` is the one-based page the segment came from; open it when a term is ambiguous. `id` is a label for your own batching and progress notes. When `--glossary` was given (see below), a segment that contains a glossary term carries a `terms` field: `{"id":"seg-00000001","src":"...","terms":{"conduction":"dẫn nhiệt"}}`. Its translation must use exactly that Vietnamese wording for that term, wherever it appears in the segment.

Read `segments.jsonl` in manageable batches. Write one JSON object per line to `translations.jsonl`:

```json
{"src":"exact source text","dst":"translated text"}
```

Copy each `src` value exactly. Preserve URLs, paths, identifiers, citation markers, and numbers. Carrying `id` and `page` through to the translated file is harmless but not required.

**`src` is what the rebuild matches on, not `id`.** A segment that appears on several pages is reported once and translated once, so a term reads the same way throughout the document. Two occurrences cannot be given different translations; if one genuinely needs different wording, say so in your report rather than editing one of them.

Formula and code placeholders look like `{v0}`, `{v1}` and stand in for a formula, an inline equation, or a code run lifted out of the text. They are immutable: every tag must reappear in `dst` with the same number, count, and relative order as in `src`. Reword the sentence around them freely, but never renumber, drop, duplicate, or reorder them. The loader rejects a record whose placeholders differ and leaves that segment untranslated.

### 3. Rebuild

```text
<python> <skill-root>/scripts/translate_pdf.py <input.pdf> --engine handoff --segments <translations.jsonl> --output-dir <output-dir> --emit-segments <still-missing.jsonl>
```

The command prints the remaining untranslated segment count. If it is nonzero, translate `still-missing.jsonl`, append valid records to `translations.jsonl`, and rebuild again. Stop only at zero or when a segment cannot be translated safely; then report the exact remaining limitation.

Extraction and rebuild each run the layout pass, so handoff uses roughly twice the local PDF processing of Google mode in addition to the agent's translation work.

## Glossary (mandatory terminology)

`--glossary <path>` gives Anthropic and Handoff mode a term list to follow instead of leaving word choice to whichever segment reaches the engine first. Google mode ignores it - the endpoint takes no instructions.

The file is JSON, one document-wide glossary per run:

```json
{
  "conduction": {"vi": "dẫn nhiệt", "domain": "heat-transfer", "locked": true},
  "premise": {"vi": "tiền đề", "domain": "logic"}
}
```

`domain` is for the glossary author's own organization; this runner does not filter by it. `locked` defaults to `true` and is not yet enforced automatically - a mismatch is something to look for in step 3 of verification below, not something the runner rejects on its own.

A malformed glossary (an entry missing a translation for the target language, invalid JSON) is rejected immediately, before the layout pass starts. In Anthropic mode, only the terms that actually occur in a given segment are added to that call's prompt; in Handoff mode, they ride along on the matching `segments.jsonl` record as `terms` (see step 2 above).

## Translation memory

Every translation (any engine) is cached by exact text, and now also by a normalized form (collapsed whitespace, Unicode NFC) so a sentence re-extracted with slightly different line-wrapping still reuses the same entry.

In Handoff mode specifically, a segment resolves in this order: (1) the `--segments` table supplied this run, (2) a translation memory entry from a *previous* run with the same language pair, (3) reported as a miss for the agent to translate. A translation supplied through step 1 is written to the translation memory, so a phrase translated once for chapter 1 does not come back as a miss for chapter 2 of the same book - and does not need re-translating at all, agent or not.

`--ignore-cache` turns this off for the current run (fresh translation everywhere, nothing read or written); `--domain <label>` tags every entry this run writes with a subject-area label for later inspection. Neither `--domain` nor which document a book entry came from currently filters lookups - v1 translation memory reuses any matching entry regardless of domain or source document, so do not rely on `--domain` to keep two unrelated books' vocabulary from mixing.

The cache lives at `~/.cache/pdf2zh/cache.v2.db` (SQLite). It has no eviction policy; delete the file to reset it.

## Verify before delivery

1. Confirm the output exists and the source still exists unchanged.
2. Confirm source and output page counts match.
3. Extract text page by page and check for substantial untranslated passages, missing formulas, damaged URLs, or lost identifiers.
4. When a `--glossary` was used, spot-check that its locked terms appear with the mandated translation in the output; report any mismatch instead of silently accepting it.
5. When page rendering or image inspection is available, render every output page and inspect for blank pages, missing glyphs, clipping, overlap, and displaced tables or figures.
6. If full visual inspection is unavailable, say which checks were completed. Do not present a partially verified or partially translated file as fully complete.
