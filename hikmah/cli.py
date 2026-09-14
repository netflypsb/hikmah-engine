#!/usr/bin/env python3
"""Hikmah Engine CLI — agent-agnostic command interface.

Usage:
    python -m hikmah ingest <file>        # Ingest a source document
    python -m hikmah lint [--fix]          # Health-check + auto-fix
    python -m hikmah graph [action]        # Wikilink graph analysis
    python -m hikmah query <question>      # Search the wiki
    python -m hikmah cascade <page>        # Cascading updates
    python -m hikmah discover <seed>       # Associative discovery
    python -m hikmah manifest              # Update MANIFEST.json
    python -m hikmah rubric <file>         # Islamic scholarly validation
    python -m hikmah rubric --all          # Validate all pages
    python -m hikmah extract <pdf>         # Extract+clean text from PDF
    python -m hikmah search <query>        # Federated cross-wiki search
    python -m hikmah bridges [--generate]  # Cross-wiki concept bridges
    python -m hikmah gates                  # Integrated quality gates
      --out FILE                           #   Write JSON report to file
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
        # lint.py uses its own argparse; reconstruct sys.argv for it
        old_argv = sys.argv
        sys.argv = ["hikmah-lint"] + args
        try:
            lint_main()
        finally:
            sys.argv = old_argv
        
    elif command == "query":
        from query import main as query_main
        old_argv = sys.argv
        sys.argv = ["hikmah-query"] + args
        try:
            query_main()
        finally:
            sys.argv = old_argv
        
    elif command == "cascade":
        print(f"[hikmah] Cascade: {args}")
        print("[hikmah] Not yet implemented — cascading updates require agent integration")
        
    elif command == "discover":
        from discover import main as discover_main
        old_argv = sys.argv
        sys.argv = ["hikmah-discover"] + args
        try:
            discover_main()
        finally:
            sys.argv = old_argv
        
    elif command == "manifest":
        print("[hikmah] Manifest update — generating MANIFEST.json")
        _generate_manifest()
        
    elif command == "rubric":
        _run_rubric(args)

    elif command == "extract":
        _run_extract(args)

    elif command == "search":
        _run_search(args)

    elif command == "graph":
        _run_graph(args)

    elif command == "bridges":
        _run_bridges(args)

    elif command == "gates":
        _run_gates(args)

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


def _run_search(args):
    """Federated search across all wikis."""
    if not args:
        print("[hikmah] Usage: python -m hikmah search <query> [--wiki NAME] [--exact] [--top N]")
        print("  Search all wikis:    python -m hikmah search tawhid")
        print("  Search one wiki:     python -m hikmah search zakat --wiki qaradawi-library")
        print("  Exact filename:      python -m hikmah search concept-zakat --exact")
        return

    from hikmah.federation import discover_wikis, federated_search

    query = args[0]
    wiki_filter = None
    exact = False
    top = 20

    i = 1
    while i < len(args):
        if args[i] == "--wiki" and i + 1 < len(args):
            wiki_filter = args[i + 1]
            i += 2
        elif args[i] == "--exact":
            exact = True
            i += 1
        elif args[i] == "--top" and i + 1 < len(args):
            top = int(args[i + 1])
            i += 2
        else:
            i += 1

    wiki_dir = os.path.join(os.getcwd(), "wiki")
    if not os.path.isdir(wiki_dir):
        print(f"[hikmah] No wiki/ directory found at {os.getcwd()}")
        return

    wikis = discover_wikis(wiki_dir)
    results = federated_search(wikis, query, exact=exact, wiki_filter=wiki_filter, top=top)

    if not results:
        print(f'[hikmah] No results for "{query}"')
        return

    print(f"\n=== Federated Search: '{query}' ===\n")
    print(f"{'Score':<8} {'Wiki':<25} {'Page':<35} {'Title':<40}")
    print("-" * 110)
    for r in results:
        print(f"{r.score:<8} {r.wiki:<25} {r.page_id:<35} {r.title[:38]:<40}")
        if r.sample:
            print(f"{'':8} {'':25} ... {r.sample}")


def _run_graph(args):
    """Build and analyze the wikilink graph."""
    from hikmah.federation import discover_wikis, build_graph, graph_summary, blast_radius, structural_gaps

    wiki_dir = os.path.join(os.getcwd(), "wiki")
    if not os.path.isdir(wiki_dir):
        print(f"[hikmah] No wiki/ directory found at {os.getcwd()}")
        return

    action = args[0] if args else "summary"

    print("[hikmah] Building wikilink graph...")
    wikis = discover_wikis(wiki_dir)
    graph = build_graph(wikis)

    if action == "summary":
        s = graph_summary(graph)
        print(f"\n=== Graph Summary ===")
        print(f"  Total pages:        {s['total_pages']}")
        print(f"  Total edges:        {s['total_edges']}")
        print(f"  Cross-wiki links:   {s['cross_wiki_links']}")
        print(f"  Orphan pages:       {s['orphan_pages']}")
        print(f"\n  Top hubs:")
        for h in s['top_hubs']:
            print(f"    {h['out_degree']:3d} links → {h['page']}: {h['title']}")
        print(f"\n  Sample orphans:")
        for o in s['top_orphans'][:5]:
            print(f"    {o['page']}: {o['title']}")

    elif action == "orphans":
        orphans = graph.orphans()
        print(f"\n=== Orphan Pages (no inbound links): {len(orphans)} ===")
        for n in sorted(orphans, key=lambda x: (x.wiki, x.page_id)):
            print(f"  {n.wiki}/{n.page_id}: {n.title}")

    elif action == "hubs":
        hubs = graph.hubs(top=20)
        print(f"\n=== Hub Pages (most outbound links) ===")
        for n in hubs:
            print(f"  {n.out_degree:3d} links → {n.wiki}/{n.page_id}: {n.title}")

    elif action == "gaps":
        print("[hikmah] Computing structural gaps (same tag, no path)...")
        gaps = structural_gaps(graph)
        if not gaps:
            print("  No structural gaps found.")
        else:
            print(f"\n=== Structural Gaps: {len(gaps)} tag(s) ===")
            for g in gaps:
                print(f"  Tag '{g['tag']}': {g['total_nodes']} nodes, {g['disconnected_pairs']} disconnected pair(s)")
                for a, b in g['examples']:
                    print(f"    {a} ↔ {b}")

    elif action == "blast":
        if len(args) < 2:
            print("[hikmah] Usage: python -m hikmah graph blast <wiki/page-id>")
            return
        node = args[1]
        result = blast_radius(graph, node)
        if "error" in result:
            print(f"  {result['error']}")
        else:
            print(f"\n=== Blast Radius: {node} ===")
            print(f"  Total reachable: {result['total_reachable']}")
            for depth, nodes in sorted(result.get("by_depth", {}).items()):
                print(f"  Hop {depth}: {len(nodes)} page(s)")
                for n in nodes[:5]:
                    print(f"    → {n}")
                if len(nodes) > 5:
                    print(f"    ... and {len(nodes) - 5} more")

    else:
        print(f"[hikmah] Unknown graph action: {action}")
        print("  Available: summary, orphans, hubs, gaps, blast <node>")


def _run_bridges(args):
    """Discover and generate cross-wiki concept bridges."""
    from hikmah.federation import discover_wikis, discover_concept_bridges, generate_bridge_markdown

    wiki_dir = os.path.join(os.getcwd(), "wiki")
    if not os.path.isdir(wiki_dir):
        print(f"[hikmah] No wiki/ directory found at {os.getcwd()}")
        return

    print("[hikmah] Discovering cross-wiki concept bridges...")
    wikis = discover_wikis(wiki_dir)
    bridges = discover_concept_bridges(wikis)

    if not bridges:
        print("  No cross-wiki concept bridges found.")
        return

    print(f"\n=== Concept Bridges: {len(bridges)} ===\n")
    print(f"{'Concept':<20} {'Arabic':<15} {'Wikis':<10} {'Pages':<6}")
    print("-" * 55)
    for b in bridges:
        print(f"{b.concept:<20} {b.arabic:<15} {len(b.wikis):<10} {len(b.pages):<6}")
        for w in b.wikis:
            count = sum(1 for p in b.pages if p.wiki == w)
            print(f"  {w}: {count} page(s)")

    # Optionally generate bridge markdown files
    if args and args[0] == "--generate":
        meta_dir = os.path.join(wiki_dir, "meta", "concepts")
        os.makedirs(meta_dir, exist_ok=True)
        for b in bridges:
            md = generate_bridge_markdown(b)
            filename = f"bridge-{b.concept}.md"
            path = os.path.join(meta_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"  Generated: {path}")


def _run_gates(args):
    """Run integrated quality gates across all wiki content."""
    from hikmah.gates import run_gates

    wiki_dir = os.path.join(os.getcwd(), "wiki")
    if not os.path.isdir(wiki_dir):
        print(f"[hikmah] No wiki/ directory found at {os.getcwd()}")
        return

    output_json = "--json" in args
    output_file = None

    i = 0
    while i < len(args):
        if args[i] == "--out" and i + 1 < len(args):
            output_file = args[i + 1]
            i += 2
        else:
            i += 1

    print("[hikmah] Running quality gates...")
    report = run_gates(wiki_dir)

    print()
    print(report.summary())

    if output_file:
        import json
        with open(output_file, "w") as f:
            json.dump(report.to_json(), f, indent=2, ensure_ascii=False)
        print(f"\n[hikmah] Full report written to {output_file}")

    # Exit code: 0 if no errors, 1 if any errors
    if report.errors > 0:
        print(f"\n[hikmah] {report.errors} ERROR(s) found — content needs attention")
    else:
        print(f"\n[hikmah] No errors — all critical gates passed")


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
