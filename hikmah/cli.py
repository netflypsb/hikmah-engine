#!/usr/bin/env python3
"""Hikmah Engine CLI — agent-agnostic command interface.

Usage:
    python -m hikmah ingest <file>        # Ingest a source document
    python -m hikmah lint [--fix]          # Health-check + auto-fix
    python -m hikmah graph                 # Rebuild knowledge graph
    python -m hikmah query <question>      # Search the wiki
    python -m hikmah cascade <page>        # Cascading updates
    python -m hikmah discover <seed>        # Associative discovery
    python -m hikmah manifest               # Update MANIFEST.json
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
        
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

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
