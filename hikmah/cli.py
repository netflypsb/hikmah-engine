#!/usr/bin/env python3
"""Hikmah Engine CLI — agent-agnostic command interface.

Usage:
    python -m hikmah ingest <file>        # Ingest a source document
    python -m hikmah lint [--fix]          # Health-check + auto-fix
    python -m hikmah graph                 # Rebuild knowledge graph
    python -m hikmah query <question>      # Search the wiki
    python -m hikmah cascade <page>        # Cascading updates
    python -m hikmah discover <seed>       # Associative discovery
    python -m hikmah manifest              # Update MANIFEST.json
    python -m hikmah rubric <file>         # Islamic scholarly validation
    python -m hikmah rubric --all          # Validate all pages
    python -m hikmah extract <pdf>         # Extract+clean text from PDF
"""
import sys
import os

# Add tools/ to path
TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    
    command = sys.argv[1]
    args = sys.argv[2:]
    
    if command == "ingest":
        print(f"[hikmah] Ingest: {' '.join(args) if args else '(no file specified)'}")
        # TODO: implement ingest via tools/ pipeline
        print("[hikmah] Not yet implemented — use tools/build.py and manual workflow for now")
        
    elif command == "lint":
        from lint import main as lint_main
        # lint.py uses its own arg parsing
        lint_main(args)
        
    elif command == "graph":
        from build import main as build_main
        build_main(["graph"] if not args else args)
        
    elif command == "query":
        from query import main as query_main
        query_main(args)
        
    elif command == "cascade":
        print(f"[hikmah] Cascade: {args}")
        print("[hikmah] Not yet implemented — cascading updates require agent integration")
        
    elif command == "discover":
        from discover import main as discover_main
        discover_main(args)
        
    elif command == "manifest":
        print("[hikmah] Manifest update — generating MANIFEST.json")
        _generate_manifest()
        
    elif command == "rubric":
        _run_rubric(args)

    elif command == "extract":
        _run_extract(args)

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

def _run_rubric(args):
    """Run Islamic scholarly rubric on wiki pages."""
    from hikmah.rubric import lint_page
    import os
    
    if not args:
        print("[hikmah] Usage: python -m hikmah rubric <file> [--all]")
        print("  Lint a single page:  python -m hikmah rubric wiki/quran-wiki/surah-001-al-fatihah.md")
        print("  Lint all pages:      python -m hikmah rubric --all")
        return
    
    if args[0] == "--all":
        wiki_dir = os.path.join(os.getcwd(), "wiki")
        if not os.path.isdir(wiki_dir):
            print(f"[hikmah] No wiki/ directory found at {os.getcwd()}")
            return
        EXCLUDE = {'.git', '.ops', '.plans', '.tools', '.config', '.cache', '.stats', 'raw', 'node_modules', 'wiki-generated', 'presentations'}
        total = 0
        passed = 0
        failed = 0
        for root, dirs, files in os.walk(wiki_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE]
            for f in files:
                if f.endswith('.md'):
                    total += 1
                    file_path = os.path.join(root, f)
                    try:
                        results = lint_page(file_path)
                        all_pass = all(r.passed for r in results)
                        if all_pass:
                            passed += 1
                        else:
                            failed += 1
                            rel = os.path.relpath(file_path, os.getcwd())
                            fails = [r.check_name for r in results if not r.passed]
                            print(f"  FAIL: {rel} — {', '.join(fails)}")
                    except Exception as e:
                        failed += 1
                        print(f"  ERROR: {file_path} — {e}")
        print()
        print(f"[hikmah] Rubric results: {total} pages, {passed} PASS, {failed} FAIL")
    else:
        file_path = args[0]
        if not os.path.exists(file_path):
            print(f"[hikmah] File not found: {file_path}")
            return
        results = lint_page(file_path)
        print(f"[hikmah] Rubric: {file_path}")
        for r in results:
            status = 'PASS' if r.passed else 'FAIL'
            print(f"  [{status}] {r.check_name}: {r.message}")
            for d in r.details:
                print(f"         {d}")


def _run_extract(args):
    """Extract and clean text from a PDF source."""
    if not args:
        print("[hikmah] Usage: python -m hikmah extract <pdf-file> [--source NAME] [--ocr] [--out DIR]")
        print("  Extract a PDF:      python -m hikmah extract sources/qaradawi/pdfs/halal-haram.pdf --source qaradawi/halal-haram")
        print("  Force OCR:           python -m hikmah extract book.pdf --source mybook --ocr")
        print("  Write chapter files: python -m hikmah extract book.pdf --source mybook --out extracted/mybook/")
        return

    from hikmah.extract import extract_and_clean

    pdf_path = args[0]
    source_name = "unknown"
    use_ocr = False
    output_dir = None

    i = 1
    while i < len(args):
        if args[i] == "--source" and i + 1 < len(args):
            source_name = args[i + 1]
            i += 2
        elif args[i] == "--ocr":
            use_ocr = True
            i += 1
        elif args[i] == "--out" and i + 1 < len(args):
            output_dir = args[i + 1]
            i += 2
        else:
            i += 1

    if not os.path.exists(pdf_path):
        print(f"[hikmah] PDF not found: {pdf_path}")
        return

    print(f"[hikmah] Extracting: {pdf_path}")
    print(f"  Source: {source_name}")
    print(f"  Method: {'OCR (forced)' if use_ocr else 'auto (pdftotext → OCR fallback)'}")

    result = extract_and_clean(
        pdf_path=pdf_path,
        source_name=source_name,
        use_ocr=use_ocr,
        output_dir=output_dir,
    )

    print(f"  Method used: {result.method}")
    print(f"  Pages: {result.total_pages}")
    print(f"  Characters: {result.total_chars:,}")
    print(f"  Chapters detected: {len(result.chapter_boundaries)}")
    print(f"  SHA-256: {result.sha256[:16]}...")

    if result.chapter_boundaries:
        print(f"  Chapter list:")
        for b in result.chapter_boundaries:
            title = b.title or "(no title)"
            print(f"    {b.num:3d}. {title}")

    if output_dir:
        print(f"  Chapter files written to: {output_dir}/")


def _generate_manifest():
    """Generate MANIFEST.json for the wiki content."""
    import json
    from datetime import datetime
    
    manifest = {
        "schema_version": "1.0.0",
        "engine_version": "2.0.0-alpha",
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "wikis": {},
        "total_curated_pages": 0
    }
    
    wiki_dir = os.path.join(os.getcwd(), "wiki")
    if os.path.isdir(wiki_dir):
        EXCLUDE = {'.git', '.ops', '.plans', '.tools', '.config', '.cache', '.stats', 'raw', 'node_modules'}
        for name in sorted(os.listdir(wiki_dir)):
            path = os.path.join(wiki_dir, name)
            if not os.path.isdir(path):
                continue
            count = 0
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in EXCLUDE]
                count += sum(1 for f in files if f.endswith('.md'))
            manifest["wikis"][name] = {"page_count": count, "v1_pages": count, "v2_pages": 0}
            manifest["total_curated_pages"] += count
    
    output = os.path.join(os.getcwd(), "MANIFEST.json")
    with open(output, 'w') as f:
        json.dump(manifest, f, indent=2)
    print(f"[hikmah] MANIFEST.json written: {manifest['total_curated_pages']} pages tracked")

if __name__ == "__main__":
    main()
