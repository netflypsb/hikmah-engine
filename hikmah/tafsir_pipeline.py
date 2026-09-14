"""Tafsir pipeline for hikmah-engine.

Converts the Quran.com tafsir JSONL corpus (Ibn Kathir EN + Muyassar AR)
into structured tafsir-entry wiki pages.

Page design:
  - One page per surah chunk (~120KB max, split by ayah ranges for long surahs)
  - Path: wiki/<wiki>/tafsir/<mufassir>/NNN-slug[-partN].md
  - Frontmatter: type: tafsir-entry, mufassir, surah_number, ayah_range
  - Body: "## Ayah N" sections with converted markdown + Arabic quote blocks
  - Provenance: ^[raw/tafsir/NNN.jsonl] per section
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


# --- HTML → Markdown ----------------------------------------------------------

_TAG_H2 = re.compile(r'<h2[^>]*>(.*?)</h2>', re.DOTALL)
_TAG_H1 = re.compile(r'<h1[^>]*>(.*?)</h1>', re.DOTALL)
_TAG_DIV = re.compile(r'</?div[^>]*>')
_TAG_P_OPEN = re.compile(r'<p[^>]*>')
_TAG_P_CLOSE = re.compile(r'</p>')
_TAG_BR = re.compile(r'<br\s*/?>')
_TAG_STRONG = re.compile(r'<(?:strong|b)[^>]*>(.*?)</(?:strong|b)>', re.DOTALL)
_TAG_EM = re.compile(r'<(?:em|i)[^>]*>(.*?)</(?:em|i)>', re.DOTALL)
_TAG_SPAN = re.compile(r'</?span[^>]*>')
_TAG_ANY = re.compile(r'<[^>]+>')


def html_to_markdown(html: str) -> str:
    """Convert simple tafsir HTML (<p>, <h1>, <h2>, <div>, <span>) to markdown."""
    text = html
    text = _TAG_H2.sub(lambda m: '\n\n### ' + m.group(1).strip() + '\n', text)
    text = _TAG_H1.sub(lambda m: '\n\n## ' + m.group(1).strip() + '\n', text)
    text = _TAG_DIV.sub('', text)
    text = _TAG_P_OPEN.sub('\n\n', text)
    text = _TAG_P_CLOSE.sub('', text)
    text = _TAG_BR.sub('\n', text)
    text = _TAG_STRONG.sub(r'**\1**', text)
    text = _TAG_EM.sub(r'*\1*', text)
    text = _TAG_SPAN.sub('', text)
    text = _TAG_ANY.sub('', text)
    text = (text.replace('&nbsp;', ' ').replace('&amp;', '&')
                .replace('&lt;', '<').replace('&gt;', '>')
                .replace('&#39;', "'").replace('&quot;', '"'))
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# --- Arabic quote detection ---------------------------------------------------

_ARABIC_RATIO = re.compile(r'[\u0600-\u06FF]')


def _is_mostly_arabic(paragraph: str) -> bool:
    """Check if a paragraph is predominantly Arabic (a quoted ayah)."""
    if not paragraph.strip():
        return False
    arabic = sum(1 for c in paragraph if 0x0600 <= ord(c) <= 0x06FF)
    letters = sum(1 for c in paragraph if c.isalpha())
    if letters == 0:
        return False
    return arabic / letters > 0.5


def format_tafsir_paragraphs(md: str) -> str:
    """Format converted markdown: Arabic quote paragraphs become blockquotes."""
    paras = re.split(r'\n\n+', md)
    out = []
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if _is_mostly_arabic(p) and len(p) < 600:
            # Arabic ayah quote — blockquote each line
            quoted = '\n'.join('> ' + ln for ln in p.split('\n'))
            out.append(quoted)
        else:
            out.append(p)
    return '\n\n'.join(out)



_QURANCOM_RE = re.compile(
    r"## Arabic Text \(Quran\.com — Cross-reference\)\s*\n+```text\s*\n(.*?)\n```",
    re.DOTALL,
)


def extract_qurancom_text(path: Path) -> Optional[str]:
    """Extract clean ayah text from the Arabic verification report files."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return None
    m = _QURANCOM_RE.search(content)
    if m:
        return m.group(1).strip()
    return None


# --- Surah metadata -----------------------------------------------------------

SURAH_NAMES = {
    1: "Al-Fatihah", 2: "Al-Baqarah", 3: "Aali Imran", 4: "An-Nisa",
    5: "Al-Ma'idah", 6: "Al-An'am", 7: "Al-A'raf", 8: "Al-Anfal",
    9: "At-Tawbah", 10: "Yunus", 11: "Hud", 12: "Yusuf", 13: "Ar-Ra'd",
    14: "Ibrahim", 15: "Al-Hijr", 16: "An-Nahl", 17: "Al-Isra",
    18: "Al-Kahf", 19: "Maryam", 20: "Taha", 21: "Al-Anbiya",
    22: "Al-Hajj", 23: "Al-Mu'minun", 24: "An-Nur", 25: "Al-Furqan",
    26: "Ash-Shu'ara", 27: "An-Naml", 28: "Al-Qasas", 29: "Al-Ankabut",
    30: "Ar-Rum", 31: "Luqman", 32: "As-Sajdah", 33: "Al-Ahzab",
    34: "Saba", 35: "Fatir", 36: "Ya-Sin", 37: "As-Saffat",
    38: "Sad", 39: "Az-Zumar", 40: "Ghafir", 41: "Fussilat",
    42: "Ash-Shura", 43: "Az-Zukhruf", 44: "Ad-Dukhan", 45: "Al-Jathiyah",
    46: "Al-Ahqaf", 47: "Muhammad", 48: "Al-Fath", 49: "Al-Hujurat",
    50: "Qaf", 51: "Adh-Dhariyat", 52: "At-Tur", 53: "An-Najm",
    54: "Al-Qamar", 55: "Ar-Rahman", 56: "Al-Waqi'ah", 57: "Al-Hadid",
    58: "Al-Mujadilah", 59: "Al-Hashr", 60: "Al-Mumtahanah",
    61: "As-Saff", 62: "Al-Jumu'ah", 63: "Al-Munafiqun", 64: "At-Taghabun",
    65: "At-Talaq", 66: "At-Tahrim", 67: "Al-Mulk", 68: "Al-Qalam",
    69: "Al-Haqqah", 70: "Al-Ma'arij", 71: "Nuh", 72: "Al-Jinn",
    73: "Al-Muzzammil", 74: "Al-Muddaththir", 75: "Al-Qiyamah",
    76: "Al-Insan", 77: "Al-Mursalat", 78: "An-Naba", 79: "An-Nazi'at",
    80: "Abasa", 81: "At-Takwir", 82: "Al-Infitar", 83: "Al-Mutaffifin",
    84: "Al-Inshiqaq", 85: "Al-Buruj", 86: "At-Tariq", 87: "Al-A'la",
    88: "Al-Ghashiyah", 89: "Al-Fajr", 90: "Al-Balad", 91: "Ash-Shams",
    92: "Al-Layl", 93: "Ad-Duha", 94: "Ash-Sharh", 95: "At-Tin",
    96: "Al-Alaq", 97: "Al-Qadr", 98: "Al-Bayyinah", 99: "Az-Zalzalah",
    100: "Al-Adiyat", 101: "Al-Qari'ah", 102: "At-Takathur",
    103: "Al-Asr", 104: "Al-Humazah", 105: "Al-Fil", 106: "Quraysh",
    107: "Al-Ma'un", 108: "Al-Kawthar", 109: "Al-Kafirun",
    110: "An-Nasr", 111: "Al-Masad", 112: "Al-Ikhlas", 113: "Al-Falaq",
    114: "An-Nas",
}



def _load_revelation():
    """Load Meccan/Medinan classification from quran metadata."""
    try:
        with open("/root/hikmah/sources/quran/metadata/quran-index.json") as f:
            meta = json.load(f)
        meccan = set(meta["revelation"]["meccan"])
        medinan = set(meta["revelation"]["medinan"])
        result = {}
        for n in range(1, 115):
            if n in meccan:
                result[n] = "makki"
            elif n in medinan:
                result[n] = "madani"
            else:
                result[n] = "makki"
        return result
    except Exception:
        return {n: ("makki" if n <= 59 else "madani") for n in range(1, 115)}


_REVELATION = _load_revelation()

def surah_slug(n: int) -> str:
    name = SURAH_NAMES.get(n, f"Surah-{n}")
    slug = re.sub(r"[^A-Za-z0-9\-]", "", name.replace(" ", "-").replace("'", ""))
    slug = re.sub(r"-+", "-", slug).lower()
    return f"{n:03d}-{slug}"


# --- Page generation ----------------------------------------------------------

@dataclass
class TafsirPage:
    surah: int
    part: int              # 1-based part number (1 if not chunked)
    total_parts: int
    ayah_start: int
    ayah_end: int
    content: str           # markdown body (without frontmatter)
    frontmatter: dict
    filename: str
    estimated_chars: int


def load_tafsir(surah: int, tafsir_root: str | Path) -> list[dict]:
    """Load ayah tafsir entries for a surah from JSONL."""
    path = Path(tafsir_root) / f"{surah:03d}.jsonl"
    if not path.exists():
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    entries.sort(key=lambda e: e["ayah"])
    return entries


def chunk_entries(entries: list[dict], target_chars: int = 120_000) -> list[list[dict]]:
    """Group ayah entries into chunks of ~target_chars (Ibn Kathir text only)."""
    chunks = []
    current = []
    current_size = 0
    for e in entries:
        e_size = sum(len(t["text"]) for t in e["tafsirs"] if "Ibn Kathir" in t["name"])
        if current and current_size + e_size > target_chars:
            chunks.append(current)
            current = []
            current_size = 0
        current.append(e)
        current_size += e_size
    if current:
        chunks.append(current)
    return chunks


def generate_page(
    surah: int,
    part_entries: list[dict],
    part_number: int,
    total_parts: int,
    mufassir: str = "ibn-kathir",
    source_rel: str = "sources/quran/tafsir",
    arabic_root: str = "/root/hikmah/sources/quran/arabic",
) -> TafsirPage:
    """Generate a single tafsir-entry page from a chunk of ayah entries."""
    ayah_start = part_entries[0]["ayah"]
    ayah_end = part_entries[-1]["ayah"]
    slug = surah_slug(surah)
    surah_name = SURAH_NAMES.get(surah, str(surah))

    part_suffix = ""
    if total_parts > 1:
        part_suffix = f"-part{part_number:02d}"
    filename = f"{slug}{part_suffix}.md"

    # Build body
    body_parts = []
    body_parts.append(
        f"# Tafsir Ibn Kathir — Surah {surah_name} ({surah}), Ayat {ayah_start}-{ayah_end}\n"
    )
    body_parts.append(
        f"> Mufassir: **Hafiz Ibn Kathir** (Abridged English) · "
        f"Source: Quran.com API v4 · "
        f"Surah {surah}, Ayat {ayah_start}–{ayah_end}"
        f"{' (part ' + str(part_number) + ' of ' + str(total_parts) + ')' if total_parts > 1 else ''}\n"
    )

    for e in part_entries:
        ayah = e["ayah"]
        ik_text = None
        muyassar_text = None
        for t in e["tafsirs"]:
            if "Ibn Kathir" in t["name"]:
                ik_text = t["text"]
            elif "Muyassar" in t["name"]:
                muyassar_text = t["text"]
        if ik_text is None:
            continue

        section = [f"## Ayah {ayah}\n"]

        # Arabic ayah text (from the Arabic corpus, Quran.com clean text)
        ar_path = Path(arabic_root) / f"{surah:03d}-{ayah:03d}.md"
        ar_text = extract_qurancom_text(ar_path) if ar_path.exists() else None
        if ar_text:
            section.append(f"> {ar_text}")

        # Ibn Kathir (main body)
        md = format_tafsir_paragraphs(html_to_markdown(ik_text))
        section.append(md)

        # Muyassar (concise Arabic tafsir)
        if muyassar_text:
            muy_md = html_to_markdown(muyassar_text)
            section.append(f"**Tafsir Muyassar (المیسر):**\n\n> {muy_md.strip()}")

        body_parts.append("\n\n".join(section))

    content = "\n\n".join(body_parts)

    # Provenance marker on the page (one source file per page — chunked JSONL)
    source_marker = f"sources/quran/tafsir/{surah:03d}.jsonl"

    frontmatter = {
        "title": f"Tafsir Ibn Kathir — Surah {surah_name} ({surah})"
                 + (f" Part {part_number}" if total_parts > 1 else ""),
        "type": "tafsir-entry",
        "mufassir": "ibn-kathir",
        "surah_number": surah,
        "surah_name": surah_name,
        "ayah_range": [ayah_start, ayah_end],
        "part": part_number,
        "total_parts": total_parts,
        "tafsir_tier": 1,
        "created": "2026-09-14",
        "updated": "2026-09-14",
        "tags": ["tafsir", "ibn-kathir", "tafsir-entry", "quran",
                 f"surah-{surah:03d}", _REVELATION.get(surah, "makki")],
        "sources": [f"raw/tafsir/{surah:03d}.jsonl"],
        "confidence": "high",
    }

    fm_lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, list):
            fm_lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        else:
            fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")

    page_content = "\n".join(fm_lines) + "\n\n" + content

    return TafsirPage(
        surah=surah,
        part=part_number,
        total_parts=total_parts,
        ayah_start=ayah_start,
        ayah_end=ayah_end,
        content=page_content,
        frontmatter=frontmatter,
        filename=filename,
        estimated_chars=len(page_content),
    )


def generate_surah_pages(
    surah: int,
    tafsir_root: str | Path,
    target_chars: int = 120_000,
) -> list[TafsirPage]:
    """Generate all tafsir pages for one surah."""
    entries = load_tafsir(surah, tafsir_root)
    if not entries:
        return []
    chunks = chunk_entries(entries, target_chars)
    pages = []
    arabic_root = str(Path(tafsir_root).parent / "arabic")
    for i, chunk in enumerate(chunks, 1):
        pages.append(generate_page(surah, chunk, i, len(chunks), arabic_root=arabic_root))
    return pages


def run_pipeline(
    tafsir_root: str | Path,
    output_dir: str | Path,
    surahs: Optional[list[int]] = None,
    target_chars: int = 120_000,
) -> dict:
    """Run the full tafsir pipeline for all surahs.

    Args:
        tafsir_root: Directory containing NNN.jsonl files
        output_dir: Output directory for generated pages
        surahs: Surah numbers to process (default: all 114)
        target_chars: Max chars per page chunk

    Returns:
        Stats dict with counts
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if surahs is None:
        surahs = list(range(1, 115))

    stats = {
        "pages_written": 0,
        "total_chars": 0,
        "surahs_processed": 0,
        "surahs_skipped": [],
        "pages_by_surah": {},
    }

    for n in surahs:
        pages = generate_surah_pages(n, tafsir_root, target_chars)
        if not pages:
            stats["surahs_skipped"] += 1
            continue
        stats["surahs_processed"] += 1
        for page in pages:
            out_path = output_dir / page.filename
            out_path.write_text(page.content, encoding="utf-8")
            stats["pages_written"] += 1
            stats["total_chars"] += page.estimated_chars
        stats["pages_by_surah"][n] = len(pages)

    return stats


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parent.parent
    tafsir_src = "/root/hikmah/sources/quran/tafsir"
    out = root / "wiki" / "quran-wiki" / "tafsir" / "ibn-kathir"
    stats = run_pipeline(tafsir_src, str(out))
    print(json.dumps(stats, indent=2))
