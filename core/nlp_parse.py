# core/nlp_parse.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

from core.utils_text import normalize_phone

DATE = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
TIME = r"(?:\d{1,2}:\d{2}(?::\d{2})?)"

DATE_RE = re.compile(DATE)
TIME_RE = re.compile(TIME)

# date range: "del 01/04/2024 al 30/04/2024", "01/04/2024 a 30/04/2024", "desde ... hasta ...", "entre ... y ..."
DATE_RANGE_RE = re.compile(
    rf"(?:del|desde|entre)?\s*({DATE})\s*(?:al|a|hasta|y)\s*({DATE})",
    re.IGNORECASE
)

# hour window: "de 21:00 a 02:00"
HOUR_WINDOW_RE = re.compile(
    rf"(?:de|entre)\s*({TIME})\s*(?:a|y|hasta)\s*({TIME})",
    re.IGNORECASE
)

PHONE_RE = re.compile(r"(\+?\d[\d\s\-]{6,16}\d)")

@dataclass
class ParsedQuery:
    phone: Optional[str]
    dt_start: Optional[datetime]
    dt_end: Optional[datetime]
    hour_start: Optional[Tuple[int,int,int]]
    hour_end: Optional[Tuple[int,int,int]]
    has_date: bool
    has_time: bool

def _parse_date(s: str) -> datetime:
    s = s.replace("-", "/")
    dd, mm, yy = s.split("/")
    dd = int(dd); mm = int(mm); yy = int(yy)
    if yy < 100:
        yy += 2000
    return datetime(yy, mm, dd)

def _parse_time_tuple(s: str) -> Tuple[int,int,int]:
    parts = s.split(":")
    hh = int(parts[0]); mi = int(parts[1]); ss = int(parts[2]) if len(parts)==3 else 0
    return hh, mi, ss

def extract_phone(text: str) -> Optional[str]:
    m = PHONE_RE.search(text)
    if not m:
        return None
    return normalize_phone(m.group(1))

def extract_datetime_range(text: str) -> Tuple[Optional[datetime], Optional[datetime], bool, bool]:
    """
    Returns (dt_start, dt_end, has_date, has_time)
    - If date range present: start at 00:00 of start date; end at 00:00 of day after end date (exclusive)
    - Else if single date present: day window
    - If date+time present (single date + single time): small window around time
    """
    text_l = text.lower()

    # 1) Date range
    m = DATE_RANGE_RE.search(text_l)
    if m:
        d1 = _parse_date(m.group(1))
        d2 = _parse_date(m.group(2))
        if d2 < d1:
            d1, d2 = d2, d1
        return d1, d2 + timedelta(days=1), True, False

    # 2) Single date
    d = DATE_RE.search(text_l)
    if not d:
        return None, None, False, False

    base = _parse_date(d.group(0))

    # If also time specified, use window
    t = TIME_RE.search(text_l)
    if t:
        hh, mi, ss = _parse_time_tuple(t.group(0))
        center = base.replace(hour=hh, minute=mi, second=ss)
        if ss != 0:
            return center, center + timedelta(seconds=1), True, True
        w = timedelta(minutes=2)
        return center - w, center + w, True, True

    return base, base + timedelta(days=1), True, False

def extract_hour_window(text: str) -> Tuple[Optional[Tuple[int,int,int]], Optional[Tuple[int,int,int]]]:
    m = HOUR_WINDOW_RE.search(text.lower())
    if not m:
        return None, None
    return _parse_time_tuple(m.group(1)), _parse_time_tuple(m.group(2))

def parse_question(text: str) -> ParsedQuery:
    phone = extract_phone(text)
    dt_start, dt_end, has_date, has_time = extract_datetime_range(text)
    hs, he = extract_hour_window(text)
    return ParsedQuery(phone=phone, dt_start=dt_start, dt_end=dt_end, hour_start=hs, hour_end=he, has_date=has_date, has_time=has_time)
