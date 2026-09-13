"""Local CDR times: preserve naive carrier time; convert explicit offsets to Mazatlan."""
from datetime import datetime, date, time, timedelta
import re
import pandas as pd

ZONE = 'America/Mazatlan'


def parse_local_datetime(value, hour=None):
    if value is None or pd.isna(value) or str(value).strip() == '':
        return pd.NaT
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not 20000 <= value <= 90000:
                return pd.NaT
            stamp = pd.Timestamp('1899-12-30') + pd.to_timedelta(value, unit='D')
        elif isinstance(value, (datetime, date, pd.Timestamp)):
            stamp = pd.Timestamp(value)
        else:
            text = str(value).strip()
            text = re.sub(r'(?i)a\.?\s*m\.?', 'AM', text)
            text = re.sub(r'(?i)p\.?\s*m\.?', 'PM', text)
            stamp = pd.to_datetime(text, dayfirst=not bool(re.match(r'^\d{4}[-/]', text)), errors='coerce')
        if pd.isna(stamp):
            return pd.NaT
        if hour is not None and pd.notna(hour) and str(hour).strip():
            if isinstance(hour, (int, float)):
                if not 0 <= hour < 1:
                    return pd.NaT
                delta = pd.to_timedelta(round(hour * 86400), unit='s')
            else:
                if isinstance(hour, time):
                    ht = hour
                else:
                    hs = str(hour).strip()
                    hs = re.sub(r'(?i)a\.?\s*m\.?', 'AM', hs)
                    hs = re.sub(r'(?i)p\.?\s*m\.?', 'PM', hs)
                    ht = pd.to_datetime(hs, errors='coerce')
                    if pd.isna(ht):
                        return pd.NaT
                    ht = ht.time()
                delta = pd.Timedelta(hours=ht.hour, minutes=ht.minute, seconds=ht.second)
            stamp = stamp.normalize() + delta
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert(ZONE).tz_localize(None)
        return stamp
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
