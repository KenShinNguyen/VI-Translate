## Expert pipeline

Use `specialized_translate.py` to combine OpenDataLoader document intelligence with VI-Translate handoff/reconstruction.

The important invariant is that VI-Translate's own handoff segments remain authoritative for `src` matching. OpenDataLoader metadata is merged onto those segments rather than replacing them.

```powershell
python scripts\specialized_translate.py "C:\Projects\book.pdf" --domain tax --glossary terminology\master_glossary.json --output-dir translated
```

Workflow:
1. OpenDataLoader extracts Markdown/JSON.
2. `opendataloader_adapter.py` normalizes ODL metadata.
3. VI-Translate emits its exact handoff source segments.
4. `merge_translation_context.py` attaches ODL type/bbox metadata.
5. An agent translates `segments.context.jsonl` into `translations.jsonl` using `translation-contract.txt`.
6. `translate_pdf.py --engine handoff --segments translations.jsonl` rebuilds the PDF.

Do not alter the `src` field while translating.
