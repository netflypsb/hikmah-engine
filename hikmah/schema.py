"""Islamic page schemas for hikmah-engine.

Extends the newsroom's generic page schema with Islamic-specific fields,
validation rules, and source tier compliance.

Page types specific to Islamic literature:
  - surah: Quran surah overview page
  - verse: Per-verse deep dive page
  - tafsir-entry: Tafsir commentary entry (per-surah or per-passage)
  - concept: Cross-cutting theological concept (tawhid, iman, akhirah, etc.)
  - linguistic: Arabic word study / root analysis
  - entity-theme: Quranic theme (prophets, stories, names of Allah, asbab al-nuzul)
  - scholar: Scholar biographical page
  - book-chapter: Book chapter wiki page (for non-Quran works)
  - cross-tafsir: Cross-tafsir comparison page
  - source: Source reflection (same as newsroom, with Islamic additions)

Source tiers (Islamic scholarly authority hierarchy):
  TIER 1: Quran + Tafsir (Ibn Kathir, Fi Zilal, al-Tabari, al-Qurtubi, etc.)
  TIER 2: Hadith (Sahih Bukhari, Muslim, Sunan, Muwatta, etc.)
  TIER 3: Classical Scholars (al-Ghazali, Ibn Taymiyyah, Ibn al-Qayyim, etc.)
  TIER 4: Contemporary Authenticated (Ibn Baz, Ibn Uthaymeen, al-Albani, Qaradawi fiqh)
  TIER 5: Islamic History (Ibn Hisham, al-Tabari, Ibn Khaldun)

Prohibited sources:
  - Shi'a sources (al-Kafi, Bihar al-Anwar)
  - Non-Muslim orientalist sources for theology
  - Weak/fabricated hadith without explicit labelling
  - Unverified websites, anonymous blogs
"""
from __future__ import annotations

# Extended frontmatter fields for Islamic pages
ISLAMIC_FRONTMATTER_FIELDS = {
    # Common to all page types
    "surah": {
        "required": ["title", "type", "surah_number", "surah_name", "revelation", "verse_count", "tags", "sources", "last_updated"],
        "optional": ["juz", "rukus", "page_start", "page_end", "arabic_name", "translation_refs", "tafsir_refs"]
    },
    "verse": {
        "required": ["title", "type", "surah_number", "ayah_number", "tags", "sources", "last_updated"],
        "optional": ["arabic_text", "translation_refs", "tafsir_refs", "asbab_al_nuzul"]
    },
    "tafsir-entry": {
        "required": ["title", "type", "surah_number", "mufassir", "tags", "sources", "last_updated"],
        "optional": ["ayah_range", "section_headings", "tafsir_tier", "arabic_terms"]
    },
    "concept": {
        "required": ["title", "type", "tags", "sources", "last_updated"],
        "optional": ["arabic_name", "arabic_root", "transliteration", "tafsir_refs", "hadith_refs", "scholar_refs"]
    },
    "linguistic": {
        "required": ["title", "type", "arabic_root", "tags", "sources", "last_updated"],
        "optional": ["arabic_word", "transliteration", "quranic_occurrences", "derived_forms"]
    },
    "entity-theme": {
        "required": ["title", "type", "tags", "sources", "last_updated"],
        "optional": ["entity_kind", "arabic_name", "quranic_references"]
    },
    "scholar": {
        "required": ["title", "type", "tags", "sources", "last_updated"],
        "optional": ["arabic_name", "birth_year", "death_year", "madhab", "works", "tier"]
    },
    "book-chapter": {
        "required": ["title", "type", "book_slug", "chapter_number", "tags", "sources", "last_updated"],
        "optional": ["author", "arabic_title", "source_language", "translated_by"]
    },
    "cross-tafsir": {
        "required": ["title", "type", "surah_number", "ayah_range", "tags", "sources", "last_updated"],
        "optional": ["tafsirs_compared", "convergence_notes", "dissent_notes"]
    },
    "source": {
        "required": ["title", "type", "tags", "source_file", "last_updated"],
        "optional": ["source_tier", "author", "work_title", "arabic_title", "published", "scraped"]
    }
}

# Source tier hierarchy (lower = higher authority)
SOURCE_TIERS = {
    1: {
        "name": "Quran and Tafsir",
        "sources": ["ibn-kathir", "fi-zilal", "al-tabari", "al-qurtubi", "al-baghawi", "al-sadi", "muyassar"],
        "description": "Quran text and classical/contemporary tafsir works"
    },
    2: {
        "name": "Hadith (Sahih Collections)",
        "sources": ["bukhari", "muslim", "nasai", "abu-dawud", "tirmidhi", "ibn-majah", "malik", "nawawi-40", "ibn-rajab-40"],
        "description": "Authentic hadith collections"
    },
    3: {
        "name": "Classical Scholars",
        "sources": ["ghazali", "ibn-taymiyyah", "ibn-al-qayyim", "nawawi", "ibn-rajab", "dhahabi", "ibn-hajar", "bayhaqi"],
        "description": "Classical Sunni scholarly works"
    },
    4: {
        "name": "Contemporary Authenticated",
        "sources": ["ibn-baz", "ibn-uthaymeen", "al-albani", "qaradawi-fiqh", "fathi-yakan", "said-hawwa", "majdi-al-hilali"],
        "description": "Contemporary Sunni scholars (verified works only)"
    },
    5: {
        "name": "Islamic History",
        "sources": ["ibn-hisham", "tabari-history", "ibn-khaldun", "masudi", "baladhuri"],
        "description": "Classical historical works"
    }
}

# Prohibited sources — must NEVER be cited as authority
PROHIBITED_SOURCES = [
    "al-kafi", "bihar-al-anwar", "shia-only",  # Shi'a sources
    "orientalist-theology",  # Non-Muslim orientalist for theology
    "unverified-website", "anonymous-blog",  # Unverified
]

# Required citation rules by claim type
CITATION_RULES = {
    "theological": {
        "min_tier": 1,
        "requires": ["quran_reference", "hadith_reference"],
        "description": "Aqeedah claims require Quran + authentic hadith"
    },
    "fiqh": {
        "min_tier": 2,
        "requires": ["source_text", "madhab_position"],
        "description": "Fiqh rulings require source text + classical madhab position"
    },
    "historical": {
        "min_tier": 5,
        "requires": ["classical_historian"],
        "description": "Historical events require classical historian citation"
    },
    "scholarly_quote": {
        "min_tier": 3,
        "requires": ["scholar_name", "work_title", "volume_page"],
        "description": "Scholar quotes need name, work, and volume/page"
    },
    "tafsir_reference": {
        "min_tier": 1,
        "requires": ["mufassir_name", "verse_range"],
        "description": "Tafsir references need mufassir and verse range"
    }
}

# Arabic text handling configuration
ARABIC_UNICODE_RANGES = [
    (0x0600, 0x06FF),   # Arabic
    (0x0750, 0x077F),   # Arabic Supplement
    (0xFB50, 0xFDFF),   # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),   # Arabic Presentation Forms-B
]

# Valid transliteration character ranges (Latin Extended for diacritics)
TRANSLIT_VALID_RANGES = [
    (0x100, 0x17F),     # Latin Extended-A (ā, ī, ū, etc.)
    (0x1E00, 0x1EFF),   # Latin Extended Additional (ḥ, ṣ, ṭ, etc.)
]

# Section headers that are Islamic-specific
ISLAMIC_SECTIONS = {
    "tafsir-entry": ["## Summary", "## Commentary", "## Key Themes", "## Connections"],
    "cross-tafsir": ["## Summary", "## Convergence", "## Dissent", "## Connections"],
    "surah": ["## Overview", "## Key Themes", "## Notable Verses", "## Connections"],
    "linguistic": ["## Root Meaning", "## Quranic Usage", "## Derived Forms", "## Connections"],
}

# Tags taxonomy for Islamic content
ISLAMIC_TAGS = [
    # Core theology
    "tawhid", "risalah", "akhirah", "iman", "amal-salih", "haqq",
    # Quranic sciences
    "tafsir", "asbab-al-nuzul", "makki", "madani", "qiraat", "balagha",
    # Quranic themes
    "sabr", "shukr", "tawakkul", "dua", "dhikr", "jihad", "dawah",
    "jannah", "jahannam", "qadr", "nur", "rahmah", "adl",
    # Literature types
    "thematic-tafsir", "literary-analysis", "social-critique", "tarbiyyah-spiritual",
    # Source attribution
    "ibn-kathir", "fi-zilal", "qaradawi", "fathi-yakan", "said-hawwa", "majdi-al-hilali",
]