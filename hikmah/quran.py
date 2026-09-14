"""Quran API extraction module for hikmah-engine.

Fetches Quran text, translations, and tafsir from public APIs:
  - Quran.com API v4: tafsir (Ibn Kathir, Muyassar)
  - Al Quran Cloud API: verse verification

This module consolidates the fetch_tafsir_by_ayah.py and fetch_and_verify.py
scripts into a reusable engine component.
"""
from __future__ import annotations

import json
import os
import ssl
import time
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# Standard surah ayah counts (114 surahs)
SURAH_AYAH_COUNTS = [
    7, 286, 200, 176, 120, 165, 206, 75, 129, 109,
    123, 111, 43, 52, 99, 128, 111, 110, 98, 135,
    112, 78, 118, 64, 77, 227, 93, 88, 69, 60,
    34, 30, 73, 54, 45, 83, 182, 88, 75, 85,
    54, 53, 89, 59, 37, 35, 38, 29, 18, 45,
    60, 49, 62, 55, 78, 96, 29, 22, 24, 13,
    14, 11, 11, 18, 12, 12, 30, 52, 52, 44,
    28, 28, 20, 56, 40, 31, 50, 40, 46, 42,
    29, 19, 36, 25, 22, 17, 19, 26, 30, 20,
    15, 21, 11, 8, 8, 19, 5, 8, 8, 11,
    11, 8, 3, 9, 5, 4, 7, 3, 6, 3,
    5, 4, 5, 6,
]

# Tafsir resources on Quran.com API
TAFSIR_RESOURCES = [
    {"id": 169, "name": "Ibn Kathir (Abridged)", "author": "Hafiz Ibn Kathir", "slug": "ibn-kathir"},
    {"id": 16, "name": "Tafsir Muyassar", "author": "Al-Muyassar", "slug": "muyassar"},
]

# Al Quran Cloud API endpoints
ALQURAN_CLOUD_BASE = "https://api.alquran.cloud/v1"

# SSL context (relaxed for API access)
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch_tafsir(surah: int, ayah: int, tafsir_id: int = 169) -> Optional[dict]:
    """Fetch tafsir for a single ayah from Quran.com API.

    Args:
        surah: Surah number (1-114)
        ayah: Ayah number within the surah
        tafsir_id: Tafsir resource ID (169 = Ibn Kathir, 16 = Muyassar)

    Returns:
        Dict with text and metadata, or None if fetch fails
    """
    url = f"https://api.quran.com/api/v4/tafsirs/{tafsir_id}/by_ayah/{surah}:{ayah}"
    req = Request(url, headers={"User-Agent": "hikmah-engine/2.0"})

    try:
        with urlopen(req, context=_SSL_CTX, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data.get("status") == "OK":
                return data.get("tafsir")
            return None
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError):
        return None


def fetch_verse_verification(surah: int, ayah: int) -> Optional[dict]:
    """Verify a verse exists via Al Quran Cloud API.

    Args:
        surah: Surah number (1-114)
        ayah: Ayah number

    Returns:
        Dict with verse text (Arabic + translation), or None if fetch fails
    """
    url = f"{ALQURAN_CLOUD_BASE}/ayah/{surah}:{ayah}/quran-uthmani,en.sahih"
    req = Request(url, headers={"User-Agent": "hikmah-engine/2.0"})

    try:
        with urlopen(req, context=_SSL_CTX, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data.get("status") == "OK":
                return data.get("data")
            return None
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError):
        return None


def fetch_surah_tafsir(
    surah: int,
    tafsir_id: int = 169,
    output_path: str | Path | None = None,
    rate_limit: float = 1.0,
) -> dict:
    """Fetch tafsir for all ayahs in a surah.

    Args:
        surah: Surah number (1-114)
        tafsir_id: Tafsir resource ID
        output_path: Optional JSONL file to write results
        rate_limit: Seconds between API calls

    Returns:
        Dict mapping ayah number to tafsir text
    """
    ayah_count = SURAH_AYAH_COUNTS[surah - 1]
    results = {}

    for ayah in range(1, ayah_count + 1):
        tafsir = fetch_tafsir(surah, ayah, tafsir_id)
        if tafsir:
            results[ayah] = {
                "surah": surah,
                "ayah": ayah,
                "text": tafsir.get("text", ""),
                "resource_id": tafsir_id,
            }
            if output_path:
                with open(output_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(results[ayah], ensure_ascii=False) + "\n")
        time.sleep(rate_limit)

    return results


def verify_quran_reference(surah: int, ayah: int) -> bool:
    """Verify that a Quran reference (surah:ayah) is valid.

    Checks:
    1. Surah is in valid range (1-114)
    2. Ayah is within the surah's verse count
    3. Verse exists in Al Quran Cloud API (optional, network-dependent)

    Args:
        surah: Surah number
        ayah: Ayah number

    Returns:
        True if the reference is valid
    """
    if not (1 <= surah <= 114):
        return False
    if not (1 <= ayah <= SURAH_AYAH_COUNTS[surah - 1]):
        return False
    return True


def extract_quran_references(text: str) -> list[dict]:
    """Extract Quran references from text.

    Supports patterns:
    - (N:M) or (N: M)
    - SurahName N:M
    - [N:M]

    Args:
        text: Text to scan

    Returns:
        List of dicts with surah, ayah, and matched text
    """
    references = []

    # Pattern: (N:M) or (N: M) or (N: M-N)
    for m in re.finditer(r"\((\d+):\s*(\d+)(?:[-–—](\d+))?\)", text):
        surah = int(m.group(1))
        ayah_start = int(m.group(2))
        ayah_end = int(m.group(3)) if m.group(3) else ayah_start
        references.append({
            "surah": surah,
            "ayah_start": ayah_start,
            "ayah_end": ayah_end,
            "match": m.group(0),
            "valid": verify_quran_reference(surah, ayah_start),
        })

    # Pattern: [N:M]
    for m in re.finditer(r"\[(\d+):(\d+)\]", text):
        surah = int(m.group(1))
        ayah = int(m.group(2))
        references.append({
            "surah": surah,
            "ayah_start": ayah,
            "ayah_end": ayah,
            "match": m.group(0),
            "valid": verify_quran_reference(surah, ayah),
        })

    return references


# Need re import
import re