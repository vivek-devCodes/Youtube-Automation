"""Font discovery with Indic/Arabic script coverage where the OS provides it."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

# Ordered candidates. Noto fonts are installed in the Docker image (fonts-noto-core).
CANDIDATES = {
    "latin": ["NotoSans-Bold.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf", "segoeuib.ttf"],
    "indic": ["NotoSansDevanagari-Bold.ttf", "Nirmala.ttc", "Nirmala.ttf", "NirmalaB.ttf", "Mangal.ttf"],
    "tamil": ["NotoSansTamil-Bold.ttf", "Nirmala.ttc", "Nirmala.ttf", "Latha.ttf"],
    "telugu": ["NotoSansTelugu-Bold.ttf", "Nirmala.ttc", "Nirmala.ttf", "Gautami.ttf"],
    "kannada": ["NotoSansKannada-Bold.ttf", "Nirmala.ttc", "Nirmala.ttf", "Tunga.ttf"],
    "malayalam": ["NotoSansMalayalam-Bold.ttf", "Nirmala.ttc", "Nirmala.ttf", "Kartika.ttf"],
    "bengali": ["NotoSansBengali-Bold.ttf", "Nirmala.ttc", "Nirmala.ttf", "Vrinda.ttf"],
    "gujarati": ["NotoSansGujarati-Bold.ttf", "Nirmala.ttc", "Nirmala.ttf", "Shruti.ttf"],
    "arabic": ["NotoSansArabic-Bold.ttf", "NotoNaskhArabic-Bold.ttf", "arialbd.ttf", "segoeuib.ttf"],
}
SCRIPT_FOR_LANG = {"hi": "indic", "mr": "indic", "ta": "tamil", "te": "telugu", "kn": "kannada", "ml": "malayalam",
                   "bn": "bengali", "gu": "gujarati", "ar": "arabic"}
SEARCH_DIRS = [
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path("/System/Library/Fonts"),
]


@lru_cache
def font_path(language: str = "en") -> str | None:
    names = CANDIDATES[SCRIPT_FOR_LANG.get(language, "latin")] + CANDIDATES["latin"]
    for name in names:
        for d in SEARCH_DIRS:
            if not d.exists():
                continue
            direct = d / name
            if direct.exists():
                return str(direct)
            hits = list(d.rglob(name))
            if hits:
                return str(hits[0])
    return None


@lru_cache(maxsize=64)
def get_font(size: int, language: str = "en") -> ImageFont.FreeTypeFont:
    path = font_path(language)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)
