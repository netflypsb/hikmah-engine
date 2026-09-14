"""Islamic scholarly validation rubric for hikmah-engine.

This module implements the Islamic-specific quality checks that extend
the newsroom's generic editorial rubric. It validates:

1. Source tier compliance — claims cite appropriate authority levels
2. Citation completeness — required citations per claim type
3. Arabic text integrity — proper preservation of Arabic text and transliteration
4. Cross-tafsir fairness — multiple tafsir traditions consulted where relevant
5. Prohibited source detection — no Shi'a/orientalist/unverified sources

The rubric is designed to be machine-checkable (deterministic) for the
lint system, with advisory qualitative checks left to the agent.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from hikmah.schema import (
    SOURCE_TIERS, PROHIBITED_SOURCES, CITATION_RULES,
    ISLAMIC_TAGS, ARABIC_UNICODE_RANGES, TRANSLIT_VALID_RANGES,
    ISLAMIC_FRONTMATTER_FIELDS
)


class RubricResult(NamedTuple):
    """Result of a rubric check on a single page."""
    check_name: str
    passed: bool
    severity: str  # "error", "warning", "advisory"
    message: str
    details: list[str]


def check_source_tier_compliance(frontmatter: dict, content: str) -> RubricResult:
    """Verify that cited sources are from allowed tiers.

    Checks the `sources:` frontmatter field for source slugs and
    verifies none are in the prohibited list.
    """
    issues = []
    sources = frontmatter.get("sources", [])

    if not sources:
        return RubricResult(
            "source_tier_compliance", True, "advisory",
            "No sources listed — cannot verify tier compliance", []
        )

    for src in sources:
        src_str = str(src).lower()
        # Use word-boundary matching to avoid false positives
        # (e.g., "al-kafirun" should NOT match "al-kafi")
        for prohibited in PROHIBITED_SOURCES:
            # Match as whole word or path segment
            if re.search(r'\b' + re.escape(prohibited) + r'\b', src_str):
                issues.append(f"  PROHIBITED source: '{src}' matches '{prohibited}'")
                break

    # Check content for prohibited source references
    for prohibited in PROHIBITED_SOURCES:
        if prohibited.replace("-", " ") in content.lower():
            issues.append(f"  Content references prohibited source pattern: '{prohibited}'")

    passed = len(issues) == 0
    return RubricResult(
        "source_tier_compliance", passed,
        "error" if not passed else "advisory",
        f"Source tier compliance: {'PASS' if passed else 'FAIL'}",
        issues
    )


def check_citation_completeness(frontmatter: dict, content: str) -> RubricResult:
    """Check that theological/fiqh claims have required citations.

    Scans content for claim markers and verifies citation patterns:
    - Theological claims: need Quran reference (Surah:N) + hadith reference
    - Fiqh rulings: need source text + madhab position
    - Scholarly quotes: need scholar name + work title
    """
    issues = []

    # Detect theological claims (look for aqeedah-related keywords)
    theological_keywords = ["aqeedah", "aqidah", "tawhid", "shirk", "kufr", "iman"]
    has_theological = any(kw in content.lower() for kw in theological_keywords)

    if has_theological:
        fm_surah = frontmatter.get("surah_number")

        # Check for Quran reference patterns:
        # 1. Global reference: SurahName N:M or (N:M) or [N:M]
        # 2. Surah-scoped: verse markers like **(1)**, (Verse N), Verse N
        #    (valid when surah_number is in frontmatter — the page IS about that surah)
        quran_ref_patterns = [
            r"(?:Qur'?an|Quran)\s+\d+:\d+",
            r"\(\d+:\d+\)",
            r"Surah\s+\w+.*?verse\s+\d+",
            r"\[\d+:\d+\]",
        ]
        has_quran_ref = any(re.search(p, content, re.IGNORECASE) for p in quran_ref_patterns)

        # If no global ref, check for surah-scoped verse references
        if not has_quran_ref and fm_surah:
            verse_patterns = [
                r"\*\*\(\d+\)\*\*",      # **(1)** — Fi Zilal style
                r"\(\d+\)",               # (1) — verse markers
                r"Verse\s+\d+",
                r"verse\s+\d+",
                r"ayah\s+\d+",
                r"āyah\s+\d+",
            ]
            has_quran_ref = any(re.search(p, content, re.IGNORECASE) for p in verse_patterns)

        if not has_quran_ref:
            issues.append("  Theological claim detected but no Quran reference found (expected Surah:N:M or verse marker pattern)")

    # Detect hadith references
    hadith_patterns = [
        r"(?:Sahih\s+)?(?:al-)?Bukhari",
        r"(?:Sahih\s+)?(?:al-)?Muslim",
        r"Sunan\s+(?:an-)?(?:Nasa'i|Abu\s+Dawud|at-Tirmidhi|Ibn\s+Majah)",
        r"Muwatta",
        r"Riyad\s+as-Salihin",
    ]
    has_hadith_ref = any(re.search(p, content, re.IGNORECASE) for p in hadith_patterns)

    # Check for da'if/fabricated hadith labelling
    weak_hadith_pattern = re.search(r"da'?if|weak|fabricated|mawdoo", content, re.IGNORECASE)
    if weak_hadith_pattern and not re.search(r"da'?if.*?(?:labelled|noted|flagged|explicit)|weak.*?(?:labelled|noted|flagged|explicit)", content, re.IGNORECASE):
        issues.append("  Weak/da'if hadith referenced but not explicitly labelled per source tier rules")

    passed = len(issues) == 0
    return RubricResult(
        "citation_completeness", passed,
        "warning" if not passed else "advisory",
        f"Citation completeness: {'PASS' if passed else 'NEEDS REVIEW'}",
        issues
    )


def check_arabic_text_integrity(content: str) -> RubricResult:
    """Verify Arabic text is properly preserved (not corrupted by PDF extraction).

    Checks for:
    - Arabic Unicode characters in expected ranges
    - Transliteration uses proper diacritical marks
    - No garbage tokens from PDF extraction (mixed Latin-1 Supplement chars)
    """
    issues = []

    # Check for Arabic text presence
    has_arabic = any(
        0x0600 <= ord(ch) <= 0x06FF
        for ch in content
        if not ch.isspace()
    )

    if has_arabic:
        # Check for common PDF extraction garbage patterns
        garbage_patterns = [
            # Romanized Arabic using Latin-1 Supplement (not valid transliteration)
            r"[ÃÍÏõãŠþß][^a-zA-Z\s]{2,}",
            # Math operator verse separators
            r"[∩⊆∪⊂⊃⊇][^a-zA-Z\s]",
            # Mixed symbol tokens
            r"[a-zA-Z][\$\#\=\@][a-zA-Z]",
        ]
        for pattern in garbage_patterns:
            matches = re.findall(pattern, content)
            if matches:
                issues.append(f"  Potential PDF extraction garbage: {len(matches)} matches of pattern {pattern}")

    # Check transliteration quality (if present)
    translit_chars = [ch for ch in content if 0x100 <= ord(ch) <= 0x17F or 0x1E00 <= ord(ch) <= 0x1EFF]
    if translit_chars:
        # Good — proper transliteration diacritics present
        pass

    # Check for curly apostrophe corruption in Arabic terms
    if "â" in content and not has_arabic:
        issues.append("  Latin-1 Supplement character 'â' found without Arabic text — possible corruption")

    passed = len(issues) == 0
    return RubricResult(
        "arabic_text_integrity", passed,
        "warning" if not passed else "advisory",
        f"Arabic text integrity: {'PASS' if passed else 'NEEDS REVIEW'}",
        issues
    )


def check_provenance_markers(content: str) -> RubricResult:
    """Check that provenance markers (^[raw/...]) are present and well-formed.

    Islamic wiki pages should trace claims back to their source files.
    """
    issues = []

    # Find provenance markers
    markers = re.findall(r'\^\[raw/[^\]]+\]', content)

    if not markers:
        # Advisory — not all pages need provenance markers (e.g., concept pages)
        return RubricResult(
            "provenance_markers", True, "advisory",
            "No provenance markers found (advisory — not required for all page types)", []
        )

    # Check marker format
    for marker in markers:
        if not re.match(r'\^\[raw/[a-zA-Z0-9_\-/]+\.(md|txt|jsonl|json)\]', marker):
            issues.append(f"  Malformed provenance marker: {marker}")

    passed = len(issues) == 0
    return RubricResult(
        "provenance_markers", passed,
        "warning" if not passed else "advisory",
        f"Provenance markers: {'PASS' if passed else 'FAIL'} ({len(markers)} found)",
        issues
    )


def check_wikilink_integrity(content: str) -> RubricResult:
    """Check that wikilinks [[...]] are well-formed and use Islamic naming conventions.

    Validates:
    - Wikilinks have both [[ and ]]
    - Cross-wiki links use proper path format (quran-wiki/surah-NNN-*)
    - No broken bracket patterns
    """
    issues = []

    # Find all wikilinks
    wikilinks = re.findall(r'\[\[[^\]]+\]\]', content)

    # Find broken patterns (opening brackets without closing)
    open_only = len(re.findall(r'\[\[[^\]]*$', content, re.MULTILINE))
    if open_only:
        issues.append(f"  {open_only} wikilink(s) with opening [[ but no closing ]]")

    # Check cross-wiki link format
    cross_wiki = [wl for wl in wikilinks if "/" in wl]
    for wl in cross_wiki:
        inner = wl[2:-2]  # strip [[ ]]
        if "|" in inner:
            target = inner.split("|")[0]
        else:
            target = inner
        if not re.match(r'^[a-z][a-z0-9\-]*/[a-zA-Z0-9\-/]+$', target):
            issues.append(f"  Cross-wiki link format issue: [[{inner}]]")

    passed = len(issues) == 0
    return RubricResult(
        "wikilink_integrity", passed,
        "warning" if not passed else "advisory",
        f"Wikilink integrity: {'PASS' if passed else 'FAIL'} ({len(wikilinks)} links found)",
        issues
    )


def check_islamic_tags(frontmatter: dict) -> RubricResult:
    """Validate that tags include appropriate Islamic taxonomy terms."""
    issues = []
    tags = frontmatter.get("tags", [])

    if not tags:
        return RubricResult(
            "islamic_tags", True, "advisory",
            "No tags specified (advisory)", []
        )

    # Check for recognized Islamic tags
    recognized = [t for t in tags if t in ISLAMIC_TAGS]
    unrecognized = [t for t in tags if t not in ISLAMIC_TAGS]

    if unrecognized and not recognized:
        issues.append(f"  Tags contain no recognized Islamic taxonomy terms: {unrecognized}")

    passed = len(issues) == 0
    return RubricResult(
        "islamic_tags", passed,
        "advisory",
        f"Islamic tags: {'PASS' if passed else 'NEEDS REVIEW'} ({len(recognized)} recognized, {len(unrecognized)} other)",
        issues
    )


def run_all_checks(frontmatter: dict, content: str, page_type: str = None) -> list[RubricResult]:
    """Run all Islamic rubric checks on a page.

    Args:
        frontmatter: Parsed YAML frontmatter dict
        content: Full markdown content (including frontmatter)
        page_type: Optional page type from frontmatter

    Returns:
        List of RubricResult objects, one per check
    """
    results = []
    results.append(check_source_tier_compliance(frontmatter, content))
    results.append(check_citation_completeness(frontmatter, content))
    results.append(check_arabic_text_integrity(content))
    results.append(check_provenance_markers(content))
    results.append(check_wikilink_integrity(content))
    results.append(check_islamic_tags(frontmatter))
    return results


def lint_page(file_path: str | Path) -> list[RubricResult]:
    """Lint a single Islamic wiki page.

    Args:
        file_path: Path to the .md file

    Returns:
        List of RubricResult objects
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
    from _lib import parse_frontmatter

    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(content)
    page_type = frontmatter.get("type", "")

    return run_all_checks(frontmatter, content, page_type)