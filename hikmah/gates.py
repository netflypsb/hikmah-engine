"""Integrated quality gates for hikmah-engine.

Combines all quality checks into a single pipeline:
  1. Islamic rubric (source tiers, citations, Arabic integrity, tags, wikilinks)
  2. Federation graph analysis (orphans, hubs, structural gaps)
  3. Quran reference validation (surah:ayah format and range checking)
  4. Provenance marker audit (^[raw/...] presence and format)
  5. Content freshness (last_updated field presence and recency)

Each gate produces a GateResult with pass/fail and severity.
The pipeline produces a GatesReport with aggregate scores.

Usage:
    from hikmah.gates import run_gates
    report = run_gates(wiki_dir="wiki")
    print(report.summary())
"""
from __future__ import annotations

import os
import re
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

from hikmah.federation import discover_wikis, build_graph, graph_summary, structural_gaps
from hikmah.rubric import lint_page, RubricResult
from hikmah.quran import extract_quran_references, verify_quran_reference


# =============================================================================
#  GATE DEFINITIONS
# =============================================================================

GATE_NAMES = [
    "source_tier_compliance",
    "citation_completeness",
    "arabic_text_integrity",
    "provenance_markers",
    "wikilink_integrity",
    "islamic_tags",
    "quran_reference_validity",
    "content_freshness",
    "orphan_pages",
    "structural_gaps",
]


@dataclass
class GateResult:
    """Result of a single quality gate check on a single page."""
    gate_name: str
    page: str  # wiki/page_id
    passed: bool
    severity: str  # "error", "warning", "advisory"
    message: str
    details: list[str] = field(default_factory=list)


@dataclass
class GatesReport:
    """Aggregate quality gate report across all pages."""
    run_date: str
    total_pages: int
    total_gates_run: int
    results: list[GateResult] = field(default_factory=list)

    # Aggregate counts
    errors: int = 0
    warnings: int = 0
    advisories: int = 0
    passed: int = 0

    # Per-gate summary
    gate_summary: dict[str, dict] = field(default_factory=dict)

    # Per-wiki summary
    wiki_summary: dict[str, dict] = field(default_factory=dict)

    def add_result(self, result: GateResult):
        self.results.append(result)
        if result.passed:
            self.passed += 1
        elif result.severity == "error":
            self.errors += 1
        elif result.severity == "warning":
            self.warnings += 1
        else:
            self.advisories += 1

    def compute_summaries(self):
        """Compute per-gate and per-wiki summaries."""
        # Per-gate
        for gate_name in GATE_NAMES:
            gate_results = [r for r in self.results if r.gate_name == gate_name]
            self.gate_summary[gate_name] = {
                "total": len(gate_results),
                "passed": sum(1 for r in gate_results if r.passed),
                "errors": sum(1 for r in gate_results if not r.passed and r.severity == "error"),
                "warnings": sum(1 for r in gate_results if not r.passed and r.severity == "warning"),
                "advisories": sum(1 for r in gate_results if not r.passed and r.severity == "advisory"),
            }

        # Per-wiki
        for r in self.results:
            wiki = r.page.split("/")[0] if "/" in r.page else "unknown"
            if wiki not in self.wiki_summary:
                self.wiki_summary[wiki] = {
                    "total": 0, "passed": 0,
                    "errors": 0, "warnings": 0, "advisories": 0,
                }
            self.wiki_summary[wiki]["total"] += 1
            if r.passed:
                self.wiki_summary[wiki]["passed"] += 1
            elif r.severity == "error":
                self.wiki_summary[wiki]["errors"] += 1
            elif r.severity == "warning":
                self.wiki_summary[wiki]["warnings"] += 1
            else:
                self.wiki_summary[wiki]["advisories"] += 1

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"=== Quality Gates Report ({self.run_date}) ===",
            f"Total pages: {self.total_pages}",
            f"Total gate checks: {self.total_gates_run}",
            f"Passed: {self.passed} | Errors: {self.errors} | Warnings: {self.warnings} | Advisories: {self.advisories}",
            "",
            "Per-Gate Breakdown:",
        ]
        for gate_name in GATE_NAMES:
            s = self.gate_summary.get(gate_name, {})
            total = s.get("total", 0)
            passed = s.get("passed", 0)
            errors = s.get("errors", 0)
            warnings = s.get("warnings", 0)
            advisories = s.get("advisories", 0)
            if total > 0:
                pass_rate = passed * 100 // total
                lines.append(
                    f"  {gate_name:30s} {passed:4d}/{total:4d} ({pass_rate:3d}%) "
                    f"E={errors} W={warnings} A={advisories}"
                )

        lines.append("")
        lines.append("Per-Wiki Breakdown:")
        for wiki, s in sorted(self.wiki_summary.items()):
            lines.append(
                f"  {wiki:25s} {s['passed']:4d}/{s['total']:4d} "
                f"E={s['errors']} W={s['warnings']} A={s['advisories']}"
            )

        return "\n".join(lines)

    def to_json(self) -> dict:
        """Serialize to JSON-serializable dict."""
        return {
            "run_date": self.run_date,
            "total_pages": self.total_pages,
            "total_gates_run": self.total_gates_run,
            "aggregate": {
                "passed": self.passed,
                "errors": self.errors,
                "warnings": self.warnings,
                "advisories": self.advisories,
            },
            "gate_summary": self.gate_summary,
            "wiki_summary": self.wiki_summary,
            "results": [
                {
                    "gate": r.gate_name,
                    "page": r.page,
                    "passed": r.passed,
                    "severity": r.severity,
                    "message": r.message,
                }
                for r in self.results if not r.passed  # Only include failures
            ],
        }


# =============================================================================
#  GATE IMPLEMENTATIONS
# =============================================================================

LAST_UPDATED_RE = re.compile(r"^(?:updated|last_updated):\s*['\"]?(\d{4}-\d{2}-\d{2})", re.MULTILINE)


def _check_content_freshness(content: str, frontmatter: dict) -> GateResult:
    """Check that the page has a last_updated field."""
    fm_updated = frontmatter.get("updated") or frontmatter.get("last_updated")
    if fm_updated:
        return GateResult(
            gate_name="content_freshness",
            page="",  # filled by caller
            passed=True,
            severity="advisory",
            message="last_updated field present",
        )

    # Check raw content for the field
    if LAST_UPDATED_RE.search(content):
        return GateResult(
            gate_name="content_freshness",
            page="",
            passed=True,
            severity="advisory",
            message="last_updated found in content",
        )

    return GateResult(
        gate_name="content_freshness",
        page="",
        passed=False,
        severity="advisory",
        message="No last_updated field found",
    )


def run_gates(wiki_dir: str | Path = "wiki") -> GatesReport:
    """Run all quality gates against the wiki content.

    Args:
        wiki_dir: Path to the wiki/ directory

    Returns:
        GatesReport with all results
    """
    wiki_dir = Path(wiki_dir)
    wikis = discover_wikis(wiki_dir)
    report = GatesReport(
        run_date=datetime.now().strftime("%Y-%m-%d"),
        total_pages=sum(len(w.pages) for w in wikis),
        total_gates_run=0,
    )

    # --- Gate 1-6: Islamic rubric (per-page) ---
    for wiki in wikis:
        for page in wiki.pages:
            page_key = f"{wiki.name}/{page.page_id}"

            try:
                rubric_results = lint_page(str(page.path))
            except Exception as e:
                report.add_result(GateResult(
                    gate_name="source_tier_compliance",
                    page=page_key,
                    passed=False,
                    severity="error",
                    message=f"Rubric error: {e}",
                ))
                continue

            for r in rubric_results:
                report.add_result(GateResult(
                    gate_name=r.check_name,
                    page=page_key,
                    passed=r.passed,
                    severity=r.severity,
                    message=r.message,
                    details=r.details,
                ))

            # --- Gate 7: Quran reference validity (per-page) ---
            refs = extract_quran_references(page.content)
            invalid = [r for r in refs if not r["valid"]]
            report.add_result(GateResult(
                gate_name="quran_reference_validity",
                page=page_key,
                passed=len(invalid) == 0,
                severity="error" if invalid else "advisory",
                message=f"{len(refs)} refs ({len(invalid)} invalid)" if refs else "No Quran references",
                details=[f"Invalid: {r['match']} (Surah {r['surah']}:{r['ayah_start']})" for r in invalid],
            ))

            # --- Gate 8: Content freshness (per-page) ---
            # Parse frontmatter
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
            try:
                from _lib import parse_frontmatter
                fm = parse_frontmatter(page.content)
            except Exception:
                fm = {}

            freshness = _check_content_freshness(page.content, fm)
            freshness.page = page_key
            report.add_result(freshness)

    # --- Gate 9: Orphan pages (graph-level) ---
    graph = build_graph(wikis)
    orphans = graph.orphans()
    for node in orphans:
        report.add_result(GateResult(
            gate_name="orphan_pages",
            page=f"{node.wiki}/{node.page_id}",
            passed=False,
            severity="advisory",
            message="No inbound wikilinks",
        ))
    # Also add passed results for non-orphans (sampled — not all 700)
    non_orphan_count = graph.page_count() - len(orphans)
    for i in range(min(non_orphan_count, 10)):  # Sample 10 passes
        report.add_result(GateResult(
            gate_name="orphan_pages",
            page="(non-orphan)",
            passed=True,
            severity="advisory",
            message="Has inbound links",
        ))

    # --- Gate 10: Structural gaps (graph-level) ---
    gaps = structural_gaps(graph)
    for gap in gaps:
        for a, b in gap.get("examples", []):
            report.add_result(GateResult(
                gate_name="structural_gaps",
                page=a,
                passed=False,
                severity="warning",
                message=f"Shares tag '{gap['tag']}' with {b} but no path",
                details=[f"Disconnected: {a} ↔ {b}"],
            ))
    if not gaps:
        report.add_result(GateResult(
            gate_name="structural_gaps",
            page="(all)",
            passed=True,
            severity="advisory",
            message="No structural gaps found",
        ))

    report.total_gates_run = len(report.results)
    report.compute_summaries()
    return report