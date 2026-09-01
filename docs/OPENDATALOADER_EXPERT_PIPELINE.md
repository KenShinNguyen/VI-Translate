# OpenDataLoader + VI-Translate Expert Pipeline

This repository can use OpenDataLoader-PDF as a document-intelligence front end and its bundled PDF core as the translation/reconstruction back end.

## Architecture

```text
source.pdf
   |
   v
OpenDataLoader-PDF
   |  OCR / reading order / tables / formulas / bbox
   v
extraction.json
   |
   v
scripts/opendataloader_adapter.py
   |  normalized JSONL segments + metadata
   v
handoff segments.jsonl
   |
   v
agent translation + terminology contract
   |
   v
translations.jsonl
   |
   v
scripts/translate_pdf.py --engine handoff
   |
   v
Vietnamese PDF
```

## Install

OpenDataLoader is intentionally kept outside the bundled `pdf2zh/` core. Install its CLI separately and make sure `opendataloader-pdf` is on PATH. VI-Translate keeps its own Python environment and bundled core.

## Run

```powershell
python scripts\specialized_translate.py "C:\Projects\book.pdf" `
  --domain tax `
  --glossary terminology\master_glossary.json `
  --output-dir "C:\Projects\book-translated"
```

For a technical book:

```powershell
python scripts\specialized_translate.py "C:\Projects\engineering.pdf" `
  --domain engineering `
  --glossary terminology\master_glossary.json
```

The orchestrator creates `.translation-work/` containing:

- `extraction/` — OpenDataLoader output
- `segments.jsonl` — handoff records
- `segments.metadata.json` — page/type/bbox sidecar
- `translation-contract.txt` — terminology and preservation contract
- `translations.jsonl` — agent-generated translations
- `still-missing.jsonl` — records that still need translation after rebuild

## Handoff contract

Each input record is one line:

```json
{"id":"seg-00000001","page":12,"src":"exact source text"}
```

Each translated record must preserve `src` exactly:

```json
{"src":"exact source text","dst":"bản dịch tiếng Việt"}
```

Formula/code placeholders such as `{v0}` are immutable. Preserve URLs, identifiers, citations and numbers. Apply the glossary consistently.

## OCR

For scanned/image-only PDFs, start OpenDataLoader's hybrid backend with OCR before running this pipeline. VI-Translate itself does not perform OCR.

## Important design rule

Do not replace the bundled `pdf2zh` core with the external PyPI `pdf2zh` package. VI-Translate validates its bundled core version and preservation ruleset. OpenDataLoader is an extraction dependency, not a PDF reconstruction dependency.
