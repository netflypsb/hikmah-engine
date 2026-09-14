"""Regression: renaming a source must not strand its claim judgments.

`claim_id` keys on the claim text alone, so a file rename leaves every id in it
untouched and the theme `claim_ids` memberships survive. Editing the claim text
still re-keys it — that orphaning is the signal forcing a re-judgment, so it is
pinned here too, or a later "fix" for rewrite churn would silently let stale
judgments ride along.
"""
import _build.contradictions as C

CLAIM = "[[Meta]] — the license restricts commercial use above a user threshold"


def _ids(root, monkeypatch, filename, claim):
    """Collect claim ids from a throwaway wiki holding one source page."""
    (root / "sources").mkdir(parents=True)
    (root / "sources" / filename).write_text(
        f"## Connections\n- contradicts: {claim}\n", encoding="utf-8")
    monkeypatch.setattr(C, "wiki", root)
    return [it["id"] for it in C._collect()]


def test_source_rename_keeps_claim_id(tmp_path, monkeypatch):
    before = _ids(tmp_path / "before", monkeypatch, "old-slug.md", CLAIM)
    after = _ids(tmp_path / "after", monkeypatch, "renamed-slug.md", CLAIM)
    assert before == after == [C._claim_id(CLAIM)]


def test_claim_text_edit_rekeys(tmp_path, monkeypatch):
    before = _ids(tmp_path / "before", monkeypatch, "s.md", CLAIM)
    after = _ids(tmp_path / "after", monkeypatch, "s.md", CLAIM + " (reaffirmed 2026-07)")
    assert before != after


def test_identical_claims_in_two_sources_are_surfaced(capsys):
    dup = C._claim_id(CLAIM)
    C._print_summary([
        {"id": dup, "type": "real", "claim": CLAIM, "source": "sources/a.md"},
        {"id": dup, "type": "real", "claim": CLAIM, "source": "sources/b.md"},
    ])
    out = capsys.readouterr().out
    assert "claim id collision" in out and dup in out
