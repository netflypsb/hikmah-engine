"""Arabic-aware PDF extraction pipeline for hikmah-engine.

This module consolidates the hardened PDF extraction and text cleanup code
from the original Islamic wiki curation workflow into reusable engine components.

Pipeline stages:
  1. Extract: pdftotext -layout OR Tesseract OCR (for image-only PDFs)
  2. Detect chapters: heuristic boundary detection (English + Arabic)
  3. Clean: remove PDF extraction artifacts (100+ hardened patterns)
  4. Structure: classify blocks (verse, hadith, heading, prose)
  5. Provenance: add ^[raw/...] markers to paragraphs

The cleanup patterns were developed across multiple real-world extraction
runs from Qaradawi Library PDFs, Fi Zilal al-Qur'an, and Fathi Yakan books.
They address:
  - PDF bullet character confusion (standalone "e" at line start)
  - OCR J/I confusion (Jman → Iman, Jslam → Islam)
  - Form feed artifacts
  - Page header/footer noise
  - Fused words (ifyou → if you, ofthe → of the, etc.)
  - Curly apostrophe normalization
  - Arabic Unicode garbage from interleaved verse blocks
  - Footnote number stripping (while preserving verse references)
  - Quranic symbol artifacts (∩ ⊆ ∪ ⊂ ⊃ etc.)
"""
from __future__ import annotations

import os
import re
import subprocess
import hashlib
from pathlib import Path
from typing import NamedTuple, Optional
from dataclasses import dataclass, field


# =============================================================================
#  STAGE 1: TEXT EXTRACTION
# =============================================================================

def extract_pdf(pdf_path: str | Path, output_path: str | Path | None = None) -> str:
    """Extract text from a PDF using pdftotext -layout.

    Args:
        pdf_path: Path to the PDF file
        output_path: Optional path to write extracted text. If None, returns text.

    Returns:
        Extracted text content

    Raises:
        FileNotFoundError: PDF doesn't exist
        RuntimeError: pdftotext fails
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["pdftotext", "-layout", str(pdf_path), str(output_path)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return output_path.read_text(encoding="utf-8", errors="replace")
    else:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True, capture_output=True, text=True
        )
        return result.stdout


def extract_pdf_ocr(pdf_path: str | Path, dpi: int = 300, batch_size: int = 20) -> str:
    """OCR an image-only PDF using Tesseract.

    Processes pages in batches to manage memory.

    Args:
        pdf_path: Path to the PDF file
        dpi: DPI for page rasterization (300 recommended for Arabic)
        batch_size: Pages per batch

    Returns:
        Extracted text with page markers
    """
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        raise RuntimeError(
            "OCR requires pdf2image and pytesseract. "
            "Install: pip install pdf2image pytesseract"
        )

    pdf_path = Path(pdf_path)
    all_text = []

    # Get page count
    from pdf2image import pdfinfo_from_path
    info = pdfinfo_from_path(str(pdf_path))
    total_pages = info["Pages"]

    for start in range(1, total_pages + 1, batch_size):
        end = min(start + batch_size - 1, total_pages)
        images = convert_from_path(
            str(pdf_path), first_page=start, last_page=end, dpi=dpi
        )
        for i, img in enumerate(images):
            page_num = start + i
            text = pytesseract.image_to_string(img)
            all_text.append(f"\n\n--- Page {page_num} ---\n\n{text}")

    return "\n".join(all_text)


def get_pdf_info(pdf_path: str | Path) -> dict:
    """Get PDF metadata using pdfinfo."""
    pdf_path = Path(pdf_path)
    result = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        check=True, capture_output=True, text=True
    )
    info = {}
    for line in result.stdout.strip().split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            info[key.strip()] = val.strip()
    return info


def sha256_file(path: str | Path) -> str:
    """Calculate SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# =============================================================================
#  STAGE 2: CHAPTER DETECTION
# =============================================================================

WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}

ENGLISH_CHAPTER_RE = re.compile(
    r"^(?:CHAPTER|Chapter)\s+"
    r"(\d+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|"
    r"Eleven|Twelve|Thirteen|Fourteen|Fifteen|Sixteen|Seventeen|Eighteen|Nineteen|Twenty)"
    r"[.:\s]*$"
    r"|"
    r"^(?:CHAPTER|Chapter)\s+"
    r"(\d+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|"
    r"Eleven|Twelve|Thirteen|Fourteen|Fifteen|Sixteen|Seventeen|Eighteen|Nineteen|Twenty)"
    r"[.:]\s*(.+)$",
    re.IGNORECASE,
)

ARABIC_CHAPTER_RE = re.compile(
    r"^\s*(?:الفصل|الباب|المبحث)\s+"
    r"(?:الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر|\d+)\s*$"
)


@dataclass
class ChapterBoundary:
    num: int
    start_line: int
    title: Optional[str] = None


def detect_chapters(text: str) -> list[ChapterBoundary]:
    """Detect chapter boundaries in extracted text.

    Supports both English (Chapter N / Chapter One) and Arabic
    (الفصل الأول / الباب الأول) heading patterns.

    Args:
        text: Full extracted text

    Returns:
        List of ChapterBoundary objects
    """
    lines = text.split("\n")
    chapters = []
    seen_nums: set[int] = set()

    # Collect all matches first, then deduplicate
    all_matches = []  # (num, line_idx, title)

    for i, line in enumerate(lines):
        stripped = line.strip()

        # English chapter headings
        m = ENGLISH_CHAPTER_RE.match(stripped)
        if m:
            # Two alternatives in regex:
            # Group 1: chapter number (no title — bare "Chapter One")
            # Group 2: chapter number, Group 3: title ("Chapter 1: The Beginning")
            if m.group(1):
                num_str = m.group(1)
                title = None
            elif m.group(2):
                num_str = m.group(2)
                title = m.group(3).strip() if m.group(3) else None
            else:
                continue

            # Skip if title is just digits (page number, not real title)
            if title and title.isdigit():
                continue

            try:
                num = int(num_str)
            except ValueError:
                num = WORD_TO_NUM.get(num_str.lower())
                if num is None:
                    continue

            all_matches.append((num, i, title))
            continue

        # Arabic chapter headings
        if ARABIC_CHAPTER_RE.match(stripped):
            all_matches.append((len(all_matches) + 1, i, stripped))

    # Deduplicate:
    # - For bare "Chapter N" (no title): use the LAST occurrence
    #   (TOC entries come first, actual chapter starts come later)
    # - For titled "Chapter N: Title": use the FIRST occurrence
    #   (titled entries are less likely duplicated in TOC)
    bare_by_num = {}  # num -> (line_idx, title)
    titled_by_num = {}

    for num, line_idx, title in all_matches:
        if title:
            if num not in titled_by_num or line_idx < titled_by_num[num][0]:
                titled_by_num[num] = (line_idx, title)
        else:
            if num not in bare_by_num or line_idx > bare_by_num[num][0]:
                bare_by_num[num] = (line_idx, title)

    # Merge: prefer titled, fall back to bare
    final_by_num = {}
    for num in set(list(bare_by_num.keys()) + list(titled_by_num.keys())):
        if num in titled_by_num:
            final_by_num[num] = titled_by_num[num]
        else:
            final_by_num[num] = bare_by_num[num]

    # Build sorted list of boundaries
    for num in sorted(final_by_num):
        line_idx, title = final_by_num[num]
        chapters.append(ChapterBoundary(num=num, start_line=line_idx, title=title))

    return chapters


def split_chapters(text: str, boundaries: list[ChapterBoundary]) -> dict[int, str]:
    """Split text into chapters at detected boundaries.

    Args:
        text: Full extracted text
        boundaries: Chapter boundaries from detect_chapters()

    Returns:
        Dict mapping chapter number to chapter text
    """
    if not boundaries:
        return {1: text}

    lines = text.split("\n")
    chapters = {}

    for idx, boundary in enumerate(boundaries):
        end_line = boundaries[idx + 1].start_line if idx + 1 < len(boundaries) else len(lines)
        chapter_lines = lines[boundary.start_line:end_line]
        chapters[boundary.num] = "\n".join(chapter_lines)

    return chapters


# =============================================================================
#  STAGE 3: TEXT CLEANUP (the hardened patterns)
# =============================================================================

# --- Arabic Unicode ranges for garbage detection ---
ARABIC_SCRIPT_RE = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)

# --- Quranic symbol artifacts from PDF extraction ---
QURANIC_SYMBOLS_RE = re.compile(
    r"[∩∪⊂⊃⊇⊄⊆∈θπρβχδεφγηικλμνοσςτυωξψζ∂∆∏∑∫√∞≈≠≤≥]"
)

# --- PDF bullet character (renders as standalone "e" at line start) ---
PDF_BULLET_RE = re.compile(r"^[ \t]*e[ \t]+", re.MULTILINE)

# --- Form feed artifacts ---
FORMFEED_RE = re.compile(r"\f+")

# --- Page header/footer patterns ---
PAGE_HEADER_RE = re.compile(
    r"^\s*\d+\s+(?:Faith and Life|Halal and Haram|Fiqh al-Zakah|"
    r"Contemporary Fatwa|Approaching the Sunnah|Economic Security|"
    r"Diversion Arts|Ethics in Islam)\s*$",
    re.MULTILINE | re.IGNORECASE
)

STANDALONE_CHAPTER_RE = re.compile(
    r"^(?:Chapter|CHAPTER)\s+(?:One|Two|Three|Four|Five|Six|Seven|Eight|"
    r"Nine|Ten|Eleven|Twelve|[0-9]+)\s*$",
    re.MULTILINE | re.IGNORECASE
)

# --- OCR J/I confusion patterns ---
J_CONFUSION_PATTERNS = [
    (re.compile(r"\bJman\b", re.IGNORECASE), "Iman"),
    (re.compile(r"\bJslam\b", re.IGNORECASE), "Islam"),
    (re.compile(r"\bJslamic\b", re.IGNORECASE), "Islamic"),
    (re.compile(r"\bJslamist\b", re.IGNORECASE), "Islamist"),
    (re.compile(r"\bJmanity\b", re.IGNORECASE), "Imanity"),
    (re.compile(r"\bJ\s+man\b", re.IGNORECASE), "Iman"),
    (re.compile(r"\bJ\s+slam\b", re.IGNORECASE), "Islam"),
    (re.compile(r"\bsLlam\b", re.IGNORECASE), "Islam"),
    (re.compile(r"\bslamic\b", re.IGNORECASE), "Islamic"),
    (re.compile(r"\bjman\b", re.IGNORECASE), "Iman"),
]

# --- Fused word patterns (from PDF line-wrap artifacts) ---
FUSED_WORDS = [
    (re.compile(r"\bifyou\b", re.IGNORECASE), "if you"),
    (re.compile(r"\bIfyou\b"), "If you"),
    (re.compile(r"\bofthe\b", re.IGNORECASE), "of the"),
    (re.compile(r"\bOfthe\b"), "Of the"),
    (re.compile(r"\btohim\b", re.IGNORECASE), "to him"),
    (re.compile(r"\bofhim\b", re.IGNORECASE), "of him"),
    (re.compile(r"\bforhim\b", re.IGNORECASE), "for him"),
    (re.compile(r"\bwithhim\b", re.IGNORECASE), "with him"),
    (re.compile(r"\bbyhim\b", re.IGNORECASE), "by him"),
    (re.compile(r"\bfromhim\b", re.IGNORECASE), "from him"),
    (re.compile(r"\binhim\b", re.IGNORECASE), "in him"),
    (re.compile(r"\bonhim\b", re.IGNORECASE), "on him"),
    (re.compile(r"\bofhimself\b", re.IGNORECASE), "of himself"),
    (re.compile(r"\btohimself\b", re.IGNORECASE), "to himself"),
    (re.compile(r"\bbyhimself\b", re.IGNORECASE), "by himself"),
    (re.compile(r"\bforhimself\b", re.IGNORECASE), "for himself"),
    (re.compile(r"\bwithhimself\b", re.IGNORECASE), "with himself"),
    (re.compile(r"\bhimselfa\b", re.IGNORECASE), "himself a"),
    (re.compile(r"\bsciel\s+ntist\b", re.IGNORECASE), "scientist"),
    (re.compile(r"\bifye\b", re.IGNORECASE), "if you"),
    (re.compile(r"\bIfye\b"), "If you"),
]

# --- 1/I OCR confusion (digit 1 rendered as capital I) ---
I_CONFUSION_PATTERNS = [
    (re.compile(r"\b1\s+created\b", re.IGNORECASE), "I created"),
    (re.compile(r"\b1\s+know\b", re.IGNORECASE), "I know"),
    (re.compile(r"\b1\s+am\b", re.IGNORECASE), "I am"),
    (re.compile(r"\b1\s+will\b", re.IGNORECASE), "I will"),
    (re.compile(r"\b1\s+have\b", re.IGNORECASE), "I have"),
]

# --- Smart quote normalization ---
SMART_QUOTE_FIXES = [
    ("€", '"'),
    ("®", '"'),
    ("«", '"'),
    ("»", '"'),
]

# --- Quran reference garbling fixes ---
QURAN_REF_FIXES = [
    (re.compile(r"\(AF\s+"), "(Al-"),
    (re.compile(r"\(Al-Bagarah", re.IGNORECASE), "(Al-Baqarah"),
    (re.compile(r"\(Al- Alaq"), "(Al-Alaq"),
    (re.compile(r"\(Al-Baga\s+To\b"), "(Al-Baqarah: 115). To"),
    (re.compile(r":\s*1-5\)"), ": 1-5)"),
]

# --- Hadith end marker fixes ---
HADITH_MARKER_FIXES = [
    (re.compile(r'""\)'), '"'),
    (re.compile(r"'\)\)"), "'"),
    (re.compile(r"\)\)"), ")"),
]

# --- Verse reference protection patterns (MUST be preserved during cleanup) ---
VERSE_REF_PATTERNS = [
    re.compile(r"\(Verse\s+\d+(?:[-–—]\d+)?\)", re.IGNORECASE),
    re.compile(r"\(Verses\s+\d+(?:[-–—]\d+)?\)", re.IGNORECASE),
    re.compile(r"\(\d+:\s*\d+(?:-\d+)?\)"),
    re.compile(r"\[\d+:\d+\]"),
    re.compile(r"Surah\s+\w+.*?verse\s+\d+", re.IGNORECASE),
    re.compile(r"S[ūu]rah\s+\d+", re.IGNORECASE),
]


def clean_text(text: str, protect_verse_refs: bool = True) -> str:
    """Apply all PDF extraction cleanup patterns to text.

    This is the consolidated cleanup function ported from the hardened
    clean_extracted.py and format_chapter.py scripts.

    Args:
        text: Raw extracted text
        protect_verse_refs: If True, verse references are protected
            before cleanup and restored after

    Returns:
        Cleaned text
    """
    # --- Protect verse references ---
    placeholders = []
    if protect_verse_refs:
        def _stash(m):
            placeholders.append(m.group(0))
            return f"__VR{len(placeholders) - 1}__"

        for pattern in VERSE_REF_PATTERNS:
            text = pattern.sub(_stash, text)

    # --- Remove form feeds ---
    text = FORMFEED_RE.sub("\n\n", text)

    # --- Remove PDF bullet dots ---
    text = PDF_BULLET_RE.sub("", text)

    # --- Fix J/I OCR confusion ---
    for pattern, replacement in J_CONFUSION_PATTERNS:
        text = pattern.sub(replacement, text)

    # --- Fix fused words ---
    for pattern, replacement in FUSED_WORDS:
        text = pattern.sub(replacement, text)

    # --- Fix 1/I OCR confusion ---
    for pattern, replacement in I_CONFUSION_PATTERNS:
        text = pattern.sub(replacement, text)

    # --- Remove page headers and footers ---
    text = PAGE_HEADER_RE.sub("", text)
    text = STANDALONE_CHAPTER_RE.sub("", text)

    # --- Normalize smart quotes ---
    for old, new in SMART_QUOTE_FIXES:
        text = text.replace(old, new)

    # --- Fix Quran reference garbling ---
    for pattern, replacement in QURAN_REF_FIXES:
        text = pattern.sub(replacement, text)

    # --- Fix hadith end markers ---
    for pattern, replacement in HADITH_MARKER_FIXES:
        text = pattern.sub(replacement, text)

    # --- Fix common inline garbling ---
    text = re.sub(r"\b\d+We\b", '"We', text)
    text = re.sub(r"\b\d+Allah\b", "Allah", text)
    text = re.sub(r"\b\d+Behold\b", "Behold", text)
    text = re.sub(r'"\)\s*This\s+is', '"). This is', text)

    # --- Strip inline footnote numbers (but not verse refs) ---
    # Pattern: word.32 → word.  (digit after punctuation after word)
    text = re.sub(r"(?<=[.,;:!?'`’])\d+\b", "", text)
    # Pattern: word32 → word  (digit attached directly to end of word, not verse ref)
    text = re.sub(r"(?<=[a-zA-Z])\d{1,3}\b", "", text)

    # --- Remove footnote/editor note blocks ---
    # Lines starting with a number followed by space and a capital letter
    text = re.sub(
        r"\n\s*\d+\s+[A-Z][^\n]*(?:\n(?!\s*\d+\s+[A-Z])[^\n]*)*?(?:—\s*Editor'?s\s*note\.?|Ibid[^\n]*)",
        "\n",
        text,
        flags=re.IGNORECASE
    )

    # --- Collapse excessive whitespace ---
    text = re.sub(r"[ \t]{3,}", "  ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    # --- Restore verse references ---
    if protect_verse_refs:
        for i, ref in enumerate(placeholders):
            text = text.replace(f"__VR{i}__", ref)

    return text.strip()


def remove_arabic_garbage_lines(text: str) -> str:
    """Remove lines containing Arabic script or Quranic symbols.

    These are typically interleaved verse blocks from two-column PDF layouts.
    Stripping leaves garbage fragments, so entire lines must be dropped.

    Args:
        text: Text potentially containing Arabic garbage lines

    Returns:
        Text with Arabic/symbol lines removed
    """
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if ARABIC_SCRIPT_RE.search(line):
            continue
        if QURANIC_SYMBOLS_RE.search(line):
            continue
        # Also drop lines with math/symbol clusters
        if re.search(r"[$#]{2,}", line):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def reflow_paragraphs(text: str) -> str:
    """Join consecutive non-blank lines into paragraphs.

    Handles:
    - Hyphenated line breaks: al-\\nAnfāl → al-Anfāl
    - Leading indentation removal
    - Single newline → space within paragraphs

    Args:
        text: Text with hard line wraps

    Returns:
        Text with proper paragraph breaks (double newline)
    """
    lines = text.split("\n")
    result = []
    current_para = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            # Blank line = paragraph break
            if current_para:
                result.append(" ".join(current_para))
                current_para = []
        else:
            # Check for hyphenated line break
            if current_para and current_para[-1].endswith("-"):
                # Remove trailing hyphen and join
                current_para[-1] = current_para[-1][:-1] + stripped
            else:
                current_para.append(stripped)

    if current_para:
        result.append(" ".join(current_para))

    return "\n\n".join(result)


# =============================================================================
#  STAGE 4: BLOCK CLASSIFICATION
# =============================================================================

VERSE_REF_RE = re.compile(r"\([A-Za-z\x27\-]+:\s*\d+[^\)]*\)")
HADITH_KEYWORDS_RE = re.compile(
    r"(?:Prophet|Messenger|hadith|narrated|al-Bukhari|Muslim|divine hadith|"
    r"Abu\s+Hurayrah|Ibn\s+(?:Umar|Abbas|Masud|Umar)|Aisha|Anas\s+ibn\s+Malik)",
    re.IGNORECASE
)


def is_verse_block(text: str) -> bool:
    """Check if a text block is a Quran verse quotation."""
    s = text.strip()
    if not s:
        return False
    has_ref = bool(VERSE_REF_RE.search(s))
    starts_quote = s.startswith('"')
    return has_ref and (starts_quote or len(s) > 60)


def is_hadith_block(text: str) -> bool:
    """Check if a text block is a hadith narration."""
    s = text.strip()
    if not s or s.startswith('"') or len(s) < 40:
        return False
    return bool(HADITH_KEYWORDS_RE.search(s))


def is_heading(text: str) -> bool:
    """Check if a short text block is a section heading."""
    s = text.strip()
    if not s or len(s) < 3 or len(s) > 55:
        return False
    if not s[0].isupper():
        return False
    if " " not in s:
        return False
    if "." in s and s.index(".") < len(s) - 5:
        return False
    if VERSE_REF_RE.search(s):
        return False
    if '"' in s:
        return False
    return True


@dataclass
class TextBlock:
    """A classified block of text."""
    kind: str  # "verse", "hadith", "heading", "prose"
    text: str


def classify_blocks(text: str) -> list[TextBlock]:
    """Split text into blocks and classify each.

    Args:
        text: Cleaned, reflowed text

    Returns:
        List of TextBlock objects
    """
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    result = []

    for block in blocks:
        if is_verse_block(block):
            result.append(TextBlock(kind="verse", text=block))
        elif is_hadith_block(block):
            result.append(TextBlock(kind="hadith", text=block))
        elif is_heading(block):
            result.append(TextBlock(kind="heading", text=block))
        else:
            result.append(TextBlock(kind="prose", text=block))

    return result


# =============================================================================
#  STAGE 5: PROVENANCE MARKERS
# =============================================================================

def add_provenance_markers(text: str, source_file: str) -> str:
    """Add ^[raw/...] provenance markers to substantive paragraphs.

    Markers are NOT added to:
    - Section headings (### ...)
    - Blank lines
    - Verse-only blocks
    - YAML frontmatter

    Args:
        text: Text to annotate
        source_file: Source file path (e.g., "raw/fi-zilal/surah-103-al-asr.md")

    Returns:
        Text with provenance markers
    """
    lines = text.split("\n")
    result = []
    in_frontmatter = False
    current_paragraph: list[str] = []

    def flush_paragraph():
        if current_paragraph:
            para = " ".join(current_paragraph)
            if para.strip() and not para.startswith("#") and not para.startswith(">"):
                para = para.rstrip() + f" ^[{source_file}]"
            result.append(para)
            current_paragraph.clear()

    for line in lines:
        stripped = line.strip()

        # Handle YAML frontmatter
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            result.append(line)
            continue
        if in_frontmatter:
            result.append(line)
            continue

        # Handle headings
        if stripped.startswith("#"):
            flush_paragraph()
            result.append(line)
            continue

        # Handle blank lines
        if not stripped:
            flush_paragraph()
            result.append(line)
            continue

        # Handle verse blocks (blockquote lines starting with >)
        if stripped.startswith(">"):
            flush_paragraph()
            result.append(line)
            continue

        # Accumulate prose
        current_paragraph.append(stripped)

    flush_paragraph()
    return "\n".join(result)


# =============================================================================
#  FULL PIPELINE
# =============================================================================

@dataclass
class ExtractionResult:
    """Result of a full extraction pipeline run."""
    source_file: str
    pdf_path: str
    method: str  # "pdftotext" or "ocr"
    total_pages: int
    total_chars: int
    chapters: dict[int, str]
    chapter_boundaries: list[ChapterBoundary]
    sha256: str


def extract_and_clean(
    pdf_path: str | Path,
    source_name: str,
    use_ocr: bool = False,
    output_dir: str | Path | None = None,
) -> ExtractionResult:
    """Run the full extraction pipeline on a PDF.

    Args:
        pdf_path: Path to the PDF file
        source_name: Source slug (e.g., "qaradawi/halal-haram")
        use_ocr: Force OCR even if pdftotext works
        output_dir: Directory to write chapter files. If None, chapters
            are only returned in the result object.

    Returns:
        ExtractionResult with all extracted and cleaned chapter text
    """
    pdf_path = Path(pdf_path)

    # Get PDF info
    info = get_pdf_info(pdf_path)
    total_pages = int(info.get("Pages", 0))
    file_hash = sha256_file(pdf_path)

    # Stage 1: Extract text
    if use_ocr:
        raw_text = extract_pdf_ocr(pdf_path)
        method = "ocr"
    else:
        try:
            raw_text = extract_pdf(pdf_path)
            if len(raw_text.strip()) < 5000:
                # Likely image-only PDF
                raw_text = extract_pdf_ocr(pdf_path)
                method = "ocr"
            else:
                method = "pdftotext"
        except (subprocess.CalledProcessError, FileNotFoundError):
            raw_text = extract_pdf_ocr(pdf_path)
            method = "ocr"

    # Stage 2: Detect chapters
    boundaries = detect_chapters(raw_text)

    # Stage 3+4: Clean and structure each chapter
    chapters = {}
    if boundaries:
        raw_chapters = split_chapters(raw_text, boundaries)
    else:
        raw_chapters = {1: raw_text}

    for num, ch_text in raw_chapters.items():
        # Full cleanup pipeline
        cleaned = clean_text(ch_text, protect_verse_refs=True)
        cleaned = remove_arabic_garbage_lines(cleaned)
        cleaned = reflow_paragraphs(cleaned)
        chapters[num] = cleaned

    # Optionally write chapter files
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        for num, ch_text in chapters.items():
            ch_path = output_dir / f"ch-{num:02d}.md"
            ch_path.write_text(ch_text, encoding="utf-8")

    return ExtractionResult(
        source_file=source_name,
        pdf_path=str(pdf_path),
        method=method,
        total_pages=total_pages,
        total_chars=sum(len(c) for c in chapters.values()),
        chapters=chapters,
        chapter_boundaries=boundaries,
        sha256=file_hash,
    )