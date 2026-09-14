"""Federation module for hikmah-engine.

Provides cross-wiki search, concept bridging, and knowledge graph
capabilities across the Islamic literature wikis in a hikmah-wiki
monorepo.

Consolidates and supersedes:
  - federated_query.py (cross-wiki full-text search)
  - graph_engine.py (NetworkX-based wikilink graph)
  - cross-wiki bridge markdown (concept mapping)

Key differences from the original tools:
  1. Operates on the hikmah-wiki monorepo structure (wiki/<wiki-name>/)
     instead of the old ~/.llm-wiki/ hub with external paths
  2. No external YAML registry — wiki discovery is filesystem-based
  3. FTS5 SQLite fallback when networkx is not available
  4. Islamic concept bridging with Arabic name matching
"""
from __future__ import annotations

import os
import re
import json
import sqlite3
import tempfile
from pathlib import Path
from collections import defaultdict, Counter
from typing import NamedTuple, Optional
from dataclasses import dataclass, field


# =============================================================================
#  WIKI DISCOVERY
# =============================================================================

# Directories to exclude when scanning for wiki content
EXCLUDE_DIRS = {
    ".git", ".ops", ".plans", ".tools", ".config", ".cache", ".stats",
    "raw", "node_modules", "wiki-generated", "presentations", ".claude",
}

# Wikilink pattern: [[target]] or [[target|display text]]
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# Frontmatter pattern
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)

# Tag extraction from frontmatter
TAG_RE = re.compile(r"^tags:\s*\[(.*?)\]", re.MULTILINE)

# Title extraction from frontmatter (single line only)
TITLE_RE = re.compile(r'^title:\s*["\']?([^\n"\']+)', re.MULTILINE)

# Arabic name pattern for concept bridging
ARABIC_NAME_RE = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]+")


@dataclass
class WikiPage:
    """A single wiki page."""
    wiki: str        # wiki name (e.g., "quran-wiki")
    page_id: str     # relative path without .md
    title: str       # extracted title
    tags: list[str]  # frontmatter tags
    path: Path       # absolute file path
    content: str = ""  # full content (loaded lazily)


@dataclass
class Wiki:
    """A single wiki in the monorepo."""
    name: str        # wiki name (directory name)
    path: Path       # absolute path to wiki directory
    pages: list[WikiPage] = field(default_factory=list)


def discover_wikis(wiki_root: str | Path) -> list[Wiki]:
    """Discover all wikis in a hikmah-wiki monorepo.

    Scans the wiki/ directory for subdirectories containing .md files.
    Each subdirectory is treated as a separate wiki.

    Args:
        wiki_root: Path to the wiki/ directory

    Returns:
        List of Wiki objects with pages loaded
    """
    wiki_root = Path(wiki_root)
    if not wiki_root.is_dir():
        return []

    wikis = []
    for entry in sorted(wiki_root.iterdir()):
        if not entry.is_dir() or entry.name in EXCLUDE_DIRS:
            continue
        wiki = Wiki(name=entry.name, path=entry)
        wiki.pages = _scan_pages(entry, entry.name)
        wikis.append(wiki)

    return wikis


def _scan_pages(wiki_dir: Path, wiki_name: str) -> list[WikiPage]:
    """Scan a wiki directory for .md files and parse their metadata."""
    pages = []
    for root, dirs, files in os.walk(wiki_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            file_path = Path(root) / f
            rel = file_path.relative_to(wiki_dir)
            page_id = str(rel).replace(".md", "")

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            title = _extract_title(content, str(file_path))
            tags = _extract_tags(content)

            pages.append(WikiPage(
                wiki=wiki_name,
                page_id=page_id,
                title=title,
                tags=tags,
                path=file_path,
                content=content,
            ))

    return pages


def _extract_title(content: str, filepath: str) -> str:
    """Extract title from frontmatter or first H1 heading."""
    fm = FRONTMATTER_RE.search(content)
    if fm:
        m = TITLE_RE.search(fm.group(1))
        if m:
            return m.group(1).strip()
    h1 = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if h1:
        return h1.group(1).strip()
    return os.path.basename(filepath).replace(".md", "")


def _extract_tags(content: str) -> list[str]:
    """Extract tags from YAML frontmatter."""
    m = TAG_RE.search(content)
    if m:
        tags_str = m.group(1)
        return [t.strip().strip('"').strip("'") for t in tags_str.split(",") if t.strip()]
    return []


# =============================================================================
#  FEDERATED SEARCH
# =============================================================================

@dataclass
class SearchResult:
    """A single search result."""
    wiki: str
    page_id: str
    title: str
    score: int
    filename_match: bool
    content_matches: int
    sample: str


def search_wiki(
    wiki: Wiki,
    query: str,
    exact: bool = False,
) -> list[SearchResult]:
    """Search a single wiki for a query string.

    Args:
        wiki: Wiki to search
        query: Search term
        exact: If True, only match filenames

    Returns:
        List of SearchResult objects
    """
    query_lower = query.lower()
    results = []

    for page in wiki.pages:
        filename_match = query_lower in page.page_id.lower()

        if exact:
            if filename_match:
                results.append(SearchResult(
                    wiki=wiki.name, page_id=page.page_id,
                    title=page.title, score=10,
                    filename_match=True, content_matches=0,
                    sample="",
                ))
            continue

        # Content search
        matches = []
        for i, line in enumerate(page.content.split("\n"), 1):
            if query_lower in line.lower():
                matches.append((i, line.strip()[:120]))

        if matches or filename_match:
            results.append(SearchResult(
                wiki=wiki.name, page_id=page.page_id,
                title=page.title,
                score=(10 if filename_match else 0) + len(matches),
                filename_match=filename_match,
                content_matches=len(matches),
                sample=matches[0][1] if matches else "",
            ))

    return results


def federated_search(
    wikis: list[Wiki],
    query: str,
    exact: bool = False,
    wiki_filter: str | None = None,
    top: int = 20,
) -> list[SearchResult]:
    """Search across all wikis for a query string.

    Args:
        wikis: List of Wiki objects to search
        query: Search term
        exact: If True, only match filenames
        wiki_filter: If set, only search this wiki
        top: Maximum results to return

    Returns:
        Ranked list of SearchResult objects
    """
    all_results = []

    for wiki in wikis:
        if wiki_filter and wiki.name != wiki_filter:
            continue
        results = search_wiki(wiki, query, exact=exact)
        all_results.extend(results)

    # Sort by score descending
    all_results.sort(key=lambda r: r.score, reverse=True)
    return all_results[:top]


# =============================================================================
#  WIKILINK GRAPH (no networkx dependency required)
# =============================================================================

@dataclass
class GraphNode:
    """A node in the wikilink graph."""
    wiki: str
    page_id: str
    title: str
    tags: list[str]
    in_degree: int = 0
    out_degree: int = 0


@dataclass
class GraphEdge:
    """An edge in the wikilink graph."""
    source_wiki: str
    source_page: str
    target: str  # raw wikilink target
    cross_wiki: bool


@dataclass
class WikilinkGraph:
    """A wikilink graph built from wiki content."""
    nodes: dict[str, GraphNode] = field(default_factory=dict)  # key: "wiki/page_id"
    edges: list[GraphEdge] = field(default_factory=list)
    cross_wiki_links: list[GraphEdge] = field(default_factory=list)

    def page_count(self) -> int:
        return len(self.nodes)

    def edge_count(self) -> int:
        return len(self.edges) + len(self.cross_wiki_links)

    def orphans(self) -> list[GraphNode]:
        """Pages with zero inbound links."""
        return [n for n in self.nodes.values() if n.in_degree == 0]

    def hubs(self, top: int = 10) -> list[GraphNode]:
        """Pages with highest out-degree."""
        return sorted(self.nodes.values(), key=lambda n: n.out_degree, reverse=True)[:top]

    def cross_wiki_count(self) -> int:
        """Number of cross-wiki links."""
        return len(self.cross_wiki_links)


def build_graph(wikis: list[Wiki]) -> WikilinkGraph:
    """Build a wikilink graph from wiki content.

    Extracts [[wikilink]] references from all pages and builds a directed
    graph. Cross-wiki links (containing "/") are tracked separately.

    Args:
        wikis: List of Wiki objects with pages loaded

    Returns:
        WikilinkGraph with nodes and edges
    """
    graph = WikilinkGraph()

    # Build node index: map page_id → "wiki/page_id" for each wiki
    page_index: dict[str, str] = {}  # local page_id → full key

    for wiki in wikis:
        for page in wiki.pages:
            key = f"{wiki.name}/{page.page_id}"
            graph.nodes[key] = GraphNode(
                wiki=wiki.name,
                page_id=page.page_id,
                title=page.title,
                tags=page.tags,
            )
            # Index both the page_id and the filename for link resolution
            page_index[f"{wiki.name}:{page.page_id}"] = key
            page_index[page.page_id] = key  # bare page_id (may collide, last wins)

    # Build edges from wikilinks
    for wiki in wikis:
        for page in wiki.pages:
            source_key = f"{wiki.name}/{page.page_id}"
            links = WIKILINK_RE.findall(page.content)

            for target in links:
                target = target.strip()

                # Cross-wiki link: contains "/" (e.g., "quran-wiki/surah-001-al-fatihah")
                if "/" in target and not target.startswith("/"):
                    # Check if target matches a known page
                    if target in page_index:
                        dest_key = page_index[target]
                        graph.edges.append(GraphEdge(
                            source_wiki=wiki.name,
                            source_page=page.page_id,
                            target=dest_key,
                            cross_wiki=True,
                        ))
                        graph.cross_wiki_links.append(GraphEdge(
                            source_wiki=wiki.name,
                            source_page=page.page_id,
                            target=dest_key,
                            cross_wiki=True,
                        ))
                        graph.nodes[dest_key].in_degree += 1
                        graph.nodes[source_key].out_degree += 1
                    else:
                        # Unresolved cross-wiki link
                        graph.cross_wiki_links.append(GraphEdge(
                            source_wiki=wiki.name,
                            source_page=page.page_id,
                            target=target,
                            cross_wiki=True,
                        ))
                        graph.nodes[source_key].out_degree += 1
                else:
                    # Local link within same wiki
                    local_key = f"{wiki.name}/{target}"
                    if local_key in graph.nodes:
                        graph.edges.append(GraphEdge(
                            source_wiki=wiki.name,
                            source_page=page.page_id,
                            target=local_key,
                            cross_wiki=False,
                        ))
                        graph.nodes[local_key].in_degree += 1
                        graph.nodes[source_key].out_degree += 1
                    elif target in page_index:
                        # Could be a cross-wiki link using bare page_id
                        dest_key = page_index[target]
                        if not dest_key.startswith(wiki.name + "/"):
                            graph.cross_wiki_links.append(GraphEdge(
                                source_wiki=wiki.name,
                                source_page=page.page_id,
                                target=dest_key,
                                cross_wiki=True,
                            ))
                        graph.nodes[dest_key].in_degree += 1
                        graph.nodes[source_key].out_degree += 1

    return graph


# =============================================================================
#  CONCEPT BRIDGING
# =============================================================================

@dataclass
class ConceptBridge:
    """A concept that appears across multiple wikis."""
    concept: str              # concept name (e.g., "tawhid")
    arabic: str = ""          # Arabic name (e.g., "توحيد")
    wikis: list[str] = field(default_factory=list)  # wikis where it appears
    pages: list[WikiPage] = field(default_factory=list)  # pages about this concept


# Islamic concepts with Arabic names for cross-wiki bridging
ISLAMIC_CONCEPTS = {
    "tawhid": "توحيد",
    "iman": "إيمان",
    "islam": "إسلام",
    "aqeedah": "عقيدة",
    "aqidah": "عقيدة",
    "akhirah": "آخرة",
    "risalah": "رسالة",
    "zakat": "زكاة",
    "zakah": "زكاة",
    "salah": "صلاة",
    "prayer": "صلاة",
    "sawm": "صوم",
    "fasting": "صوم",
    "hajj": "حج",
    "pilgrimage": "حج",
    "riba": "ربا",
    "usury": "ربا",
    "halal": "حلال",
    "haram": "حرام",
    "jihad": "جهاد",
    "dawah": "دعوة",
    "sunnah": "سنة",
    "hadith": "حديث",
    "sharia": "شريعة",
    "shariah": "شريعة",
    "fiqh": "فقه",
    "sabr": "صبر",
    "patience": "صبر",
    "shukr": "شكر",
    "gratitude": "شكر",
    "tawakkul": "توكل",
    "taqwa": "تقوى",
    "akhlaq": "أخلاق",
    "character": "أخلاق",
    "adab": "أدب",
    "niyyah": "نية",
    "intention": "نية",
    "tazkiyah": "تزكية",
    "ijma": "إجماع",
    "consensus": "إجماع",
    "qiyas": "قياس",
    "ijtihad": "اجتهاد",
    "nikah": "نكاح",
    "marriage": "نكاح",
    "talaq": "طلاق",
    "divorce": "طلاق",
}


def discover_concept_bridges(wikis: list[Wiki]) -> list[ConceptBridge]:
    """Discover concepts that appear across multiple wikis.

    Scans page tags, titles, and content for Islamic concept keywords
    and groups pages by concept.

    Args:
        wikis: List of Wiki objects

    Returns:
        List of ConceptBridge objects, sorted by number of wikis
    """
    concept_pages: dict[str, list[WikiPage]] = defaultdict(list)

    for wiki in wikis:
        for page in wiki.pages:
            # Check tags for concept keywords
            page_concepts = set()
            for tag in page.tags:
                tag_lower = tag.lower()
                if tag_lower in ISLAMIC_CONCEPTS:
                    page_concepts.add(tag_lower)

            # Also check title for concept names
            title_lower = page.title.lower()
            for concept in ISLAMIC_CONCEPTS:
                if concept in title_lower and concept not in page_concepts:
                    page_concepts.add(concept)

            # Also check content for Arabic names (more expensive)
            if page.content:
                for concept, arabic in ISLAMIC_CONCEPTS.items():
                    if arabic in page.content and concept not in page_concepts:
                        page_concepts.add(concept)

            for concept in page_concepts:
                concept_pages[concept].append(page)

    # Build bridges for concepts appearing in 2+ wikis
    bridges = []
    for concept, pages in concept_pages.items():
        wiki_names = list(set(p.wiki for p in pages))
        if len(wiki_names) >= 2:
            bridges.append(ConceptBridge(
                concept=concept,
                arabic=ISLAMIC_CONCEPTS.get(concept, ""),
                wikis=sorted(wiki_names),
                pages=pages,
            ))

    bridges.sort(key=lambda b: len(b.wikis), reverse=True)
    return bridges


def generate_bridge_markdown(bridge: ConceptBridge) -> str:
    """Generate a markdown cross-wiki bridge page for a concept.

    Args:
        bridge: ConceptBridge object

    Returns:
        Markdown content for the bridge page
    """
    lines = [
        f"---",
        f'title: "Cross-Wiki Bridge — {bridge.concept.capitalize()} ({bridge.arabic})"',
        f"type: meta",
        f"tags: [meta, cross-wiki, concept, {bridge.concept}]",
        f"---",
        f"",
        f"# Cross-Wiki Bridge: {bridge.concept.capitalize()} ({bridge.arabic})",
        f"",
        f"> This concept appears across {len(bridge.wikis)} wikis in the Hikmah corpus.",
        f"",
        f"## Pages by Wiki",
        f"",
    ]

    for wiki_name in bridge.wikis:
        wiki_pages = [p for p in bridge.pages if p.wiki == wiki_name]
        lines.append(f"### {wiki_name} ({len(wiki_pages)} page(s))")
        lines.append("")
        for page in sorted(wiki_pages, key=lambda p: p.page_id):
            lines.append(f"- [[{wiki_name}/{page.page_id}|{page.title}]]")
        lines.append("")

    lines.append("## Concept Details")
    lines.append("")
    lines.append(f"**Arabic:** {bridge.arabic}")
    lines.append(f"**Concept:** {bridge.concept}")
    lines.append(f"**Wikis:** {', '.join(bridge.wikis)}")
    lines.append(f"**Total pages:** {len(bridge.pages)}")
    lines.append("")

    return "\n".join(lines)


# =============================================================================
#  GRAPH ANALYSIS
# =============================================================================

def blast_radius(graph: WikilinkGraph, node_key: str, max_depth: int = 3) -> dict:
    """Compute blast radius: what pages are affected if a node changes.

    Uses BFS to find all pages reachable from the given node via outbound links.

    Args:
        graph: WikilinkGraph
        node_key: Node key (e.g., "quran-wiki/surah-001-al-fatihah")
        max_depth: Maximum BFS depth

    Returns:
        Dict with reachable nodes grouped by depth
    """
    if node_key not in graph.nodes:
        return {"error": f"Node '{node_key}' not found"}

    # Build adjacency list for BFS
    adj: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        adj[edge.source_page].append(edge.target)
    for edge in graph.cross_wiki_links:
        if edge.target in graph.nodes:
            adj[f"{edge.source_wiki}/{edge.source_page}"].append(edge.target)

    # BFS
    visited = {node_key}
    by_depth: dict[int, list[str]] = {}
    current_level = [node_key]

    for depth in range(1, max_depth + 1):
        next_level = []
        for node in current_level:
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_level.append(neighbor)
        if next_level:
            by_depth[depth] = next_level
            current_level = next_level
        else:
            break

    return {
        "node": node_key,
        "total_reachable": sum(len(v) for v in by_depth.values()),
        "by_depth": by_depth,
    }


def structural_gaps(graph: WikilinkGraph) -> list[dict]:
    """Find pages sharing tags but with no wikilink path between them.

    Args:
        graph: WikilinkGraph

    Returns:
        List of gap dicts with tag and disconnected pairs
    """
    # Group nodes by tag
    by_tag: dict[str, list[str]] = defaultdict(list)
    for key, node in graph.nodes.items():
        for tag in node.tags:
            by_tag[tag].append(key)

    # Build undirected adjacency for path checking
    adj: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        adj[edge.source_page].add(edge.target)
        adj[edge.target].add(edge.source_page)
    for edge in graph.cross_wiki_links:
        if edge.target in graph.nodes:
            src_key = f"{edge.source_wiki}/{edge.source_page}"
            adj[src_key].add(edge.target)
            adj[edge.target].add(src_key)

    gaps = []
    for tag, nodes in by_tag.items():
        if len(nodes) < 2:
            continue
        disconnected_pairs = []
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                # Simple BFS path check
                if not _has_path(adj, a, b):
                    disconnected_pairs.append((a, b))
        if disconnected_pairs:
            gaps.append({
                "tag": tag,
                "total_nodes": len(nodes),
                "disconnected_pairs": len(disconnected_pairs),
                "examples": disconnected_pairs[:5],
            })

    return gaps


def _has_path(adj: dict[str, set[str]], start: str, end: str, max_hops: int = 10) -> bool:
    """Check if there's a path between two nodes (BFS, limited depth)."""
    if start == end:
        return True
    visited = {start}
    current = [start]
    for _ in range(max_hops):
        next_level = []
        for node in current:
            for neighbor in adj.get(node, set()):
                if neighbor == end:
                    return True
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_level.append(neighbor)
        if not next_level:
            break
        current = next_level
    return False


def graph_summary(graph: WikilinkGraph) -> dict:
    """Generate a summary of the graph."""
    orphans = graph.orphans()
    hubs = graph.hubs(top=5)

    return {
        "total_pages": graph.page_count(),
        "total_edges": graph.edge_count(),
        "cross_wiki_links": graph.cross_wiki_count(),
        "orphan_pages": len(orphans),
        "top_hubs": [
            {"page": f"{n.wiki}/{n.page_id}", "title": n.title, "out_degree": n.out_degree}
            for n in hubs
        ],
        "top_orphans": [
            {"page": f"{n.wiki}/{n.page_id}", "title": n.title}
            for n in sorted(orphans, key=lambda x: x.page_id)[:10]
        ],
    }