# Hikmah Engine

**Islamic Literature LLM Wiki Engine** — a multi-agent knowledge production system for Islamic scholarly texts.

Forked from [llm-wiki-newsroom](https://github.com/alfadur7/llm-wiki-newsroom) by alfadur7 (MIT license). Adapted for Arabic/English Islamic scholarship with bilingual schema, tafsir tier validation, Arabic-aware PDF extraction, and federated multi-wiki architecture.

## What This Does

Drop Islamic source texts (Quran corpus, tafsir works, scholarly books) into `raw/`, run a command, and the engine reads them, extracts entities, concepts, and relationships, and organizes everything into a fully cross-referenced wiki — a structured and persistent alternative to RAG for Islamic knowledge.

## Key Adaptations from the Original

| Feature | Original (Newsroom) | Hikmah Engine |
|---------|-------------------|----------------|
| Schema language | English-only tokens | Bilingual Arabic/English |
| Editorial rubric | Journalism/consulting | Islamic scholarly (source tiers, citation rules) |
| PDF handling | Basic (agent reads directly) | Hardened Arabic-aware pipeline (100+ garbage token catalog, valid-char allowlist, 4-pass cleanup) |
| Wiki architecture | Single wiki per repo | Federated multi-wiki (quran-wiki ↔ fi-zilal ↔ qaradawi ↔ jeel-mawoud) |
| Agent integration | Claude Code slash commands | Agent-agnostic CLI (works with any agent or human) |
| Source validation | Generic quality checks | Islamic source tier system (Quran > Sahih Hadith > Classical Scholars > Contemporary) |
| Reprocessing | N/A | Per-page versioning with MANIFEST.json (v1.0 manual → v2.0 engine) |

## What We Kept from the Original

- Four-loop architecture (inner self-check, outer publication gate, meta rule evolution, reground staleness)
- Five-role newsroom (reporter, columnist, copy editor, desk, editor-in-chief)
- Cascading updates (ingesting 1 document refreshes 10-15 related pages)
- Leiden community detection for automatic topic clustering
- Interactive knowledge graph (Sigma.js)
- Deterministic lint system (Python, no API keys)
- Contradiction detection (3-layer tracking)
- GROUND Ladder reading discipline
- Query tools (graph traversal + BM25 + semantic search)
- Memex-style associative discovery

## Installation

```bash
git clone https://github.com/netflypsb/hikmah-engine.git
cd hikmah-engine
pip install -r requirements.txt
```

No API keys required. The Python tools run locally.

## Usage

The engine exposes an agent-agnostic CLI:

```bash
python -m hikmah ingest <file>           # ingest a new source
python -m hikmah lint [--fix]            # health-check + auto-fix
python -m hikmah graph                   # rebuild knowledge graph
python -m hikmah query <question>        # search the wiki
python -m hikmah cascade <page>          # trigger cascading updates
python -m hikmah discover <seed>          # associative discovery
python -m hikmah manifest                # update MANIFEST.json
```

Any agent (Claude Code, Hermes, Codex, Gemini) or human can invoke these commands. See `AGENTS.md` for integration instructions.

## Source Material

Original Islamic reference texts are published on [Bayt al-Hikmah](https://bayt-al-hikmah-nine.vercel.app/) — a project to bring Islamic references into website format and translate them into many languages.

See `BAYT_AL_HIKMAH.md` for details.

## License

MIT (inherited from llm-wiki-newsroom)

## Acknowledgements

- [llm-wiki-newsroom](https://github.com/alfadur7/llm-wiki-newsroom) by alfadur7 — the original newsroom architecture
- [Andrej Karpathy's LLM Wiki concept](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — the three-layer pattern