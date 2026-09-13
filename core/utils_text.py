# core/utils_text.py
from __future__ import annotations
import re
import unicodedata
from typing import Any, Optional

def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))

def norm_col(s: Any) -> str:
    s = "" if s is None else str(s)
    s = strip_accents(s).lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s

def only_digits(s: Any) -> str:
    if s is None:
        return ""
    return re.sub(r"\D", "", str(s))

def normalize_phone(x: Any) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    d = only_digits(s)
    if not d:
        return None
    # Mexico-ish normalization: keep last 10 if startswith 52 and length >= 11
    if len(d) in (11, 12) and d.startswith("52"):
        d = d[-10:]
    if len(d) == 10:
        return d
    # Keep as-is for other lengths
    return d
