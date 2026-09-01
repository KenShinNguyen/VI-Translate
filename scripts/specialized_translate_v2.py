#!/usr/bin/env python3
"""Expert pipeline: OpenDataLoader context + VI-Translate authoritative handoff."""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ADAPTER = HERE / "opendataloader_adapter.py"
MERGER = HERE / "merge_translation_context.py"
TRANSLATOR = HERE / "translate_pdf.py"

def run(cmd: list[str]) -> None:
    print("+", subprocess.list2cmdline(cmd))
    subprocess.run(cmd, check=True)

def main() -> int:
    p=argparse.ArgumentParser(description="OpenDataLoader context + VI-Translate expert handoff")
    p.add_argument("input_pdf", type=Path); p.add_argument("--output-dir",type=Path,default=Path("translated"))
    p.add_argument("--work-dir",type=Path,default=Path(".translation-work")); p.add_argument("--domain",default="general")
    p.add_argument("--glossary",type=Path); p.add_argument("--odl-command"); p.add_argument("--pages"); p.add_argument("--threads",type=int,default=4)
    args=p.parse_args(); source=args.input_pdf.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".pdf": raise SystemExit(f"Invalid PDF: {source}")
    work=args.work_dir.expanduser().resolve(); extract=work/"extraction"; extract.mkdir(parents=True,exist_ok=True)
    odl_segments=work/"odl-segments.jsonl"; metadata=work/"segments.metadata.json"; vi_segments=work/"vi-segments.jsonl"; context=work/"segments.context.jsonl"; contract=work/"translation-contract.txt"; translations=work/"translations.jsonl"; missing=work/"still-missing.jsonl"
    odl=args.odl_command or shutil.which("opendataloader-pdf")
    if not odl: raise SystemExit("OpenDataLoader CLI not found. Install it or pass --odl-command.")
    run([odl,str(source),"-f","markdown,json","-o",str(extract)])
    files=sorted(extract.rglob("*.json"));
    if not files: raise SystemExit(f"No JSON output from OpenDataLoader: {extract}")
    match=[f for f in files if f.stem.lower()==source.stem.lower()]; js=match[0] if match else max(files,key=lambda f:f.stat().st_size)
    run([sys.executable,str(ADAPTER),str(js),str(odl_segments),"--metadata",str(metadata)])
    cmd=[sys.executable,str(TRANSLATOR),str(source),"--engine","handoff","--emit-segments",str(vi_segments),"--threads",str(args.threads)]
    if args.pages: cmd += ["--pages",args.pages]
    run(cmd)
    run([sys.executable,str(MERGER),str(vi_segments),str(metadata),str(context)])
    glossary={}
    if args.glossary:
        data=json.loads(args.glossary.read_text(encoding="utf-8")); glossary=data.get("terms",data) if isinstance(data,dict) else {}
    lines=["EXPERT TRANSLATION CONTRACT",f"Domain: {args.domain}","Translate English to Vietnamese.","Preserve meaning, logical relations, certainty, numbers, citations, URLs, identifiers and placeholders exactly.","Never modify {v0}, {v1}, etc.","Use preferred terminology consistently.","","PREFERRED TERMINOLOGY:"]+[f"{k} -> {v}" for k,v in glossary.items()]
    contract.write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"\nTranslate: {context}\nContract: {contract}\nWrite output to: {translations}")
    rebuild=[sys.executable,str(TRANSLATOR),str(source),"--engine","handoff","--segments",str(translations),"--output-dir",str(args.output_dir),"--emit-segments",str(missing)]
    print("Rebuild:"); print(subprocess.list2cmdline(rebuild))
    return 0
if __name__ == "__main__": raise SystemExit(main())
