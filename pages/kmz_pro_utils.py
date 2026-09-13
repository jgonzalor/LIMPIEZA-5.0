# -*- coding: utf-8 -*-
"""
Utilidades geoespaciales y normalización para Sentinel Mapper KMZ Pro.

Este módulo no depende de Streamlit. Puede reutilizarse desde otros módulos.
"""

from __future__ import annotations

import math
import re
from typing import Iterable, Optional, Tuple

import pandas as pd


EARTH_RADIUS_M = 6371008.8


def clean_colname(name: object) -> str:
    """Normaliza nombres de columnas para búsquedas flexibles."""
    txt = str(name or "").strip().lower()
    rep = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ñ": "n", "\n": " ", "\r": " ", "\t": " ",
    }
    for a, b in rep.items():
        txt = txt.replace(a, b)
    txt = re.sub(r"[^a-z0-9]+", "_", txt)
    txt = re.sub(r"_+", "_", txt).strip("_")
    return txt


def first_existing_column(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    """Busca una columna por lista de candidatos, tolerando acentos, espacios y variantes."""
    if df is None or df.empty:
        return None

    norm_map = {clean_colname(c): c for c in df.columns}
    cand_norms = [clean_colname(c) for c in candidates]

    for c in cand_norms:
        if c in norm_map:
            return norm_map[c]

    # búsqueda parcial conservadora
    for c in cand_norms:
        for norm, original in norm_map.items():
            if c and (c == norm or c in norm or norm in c):
                return original
    return None


def to_float(value) -> Optional[float]:
    """Convierte coordenadas o números a float, tolerando texto con comas y basura."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    txt = str(value).strip()
    if not txt or txt.lower() in {"nan", "none", "null", "sin dato", "s/d"}:
        return None

    # Si viene como "[25.12345]" o "Lat:25.123"
    txt = txt.replace(",", ".")
    found = re.findall(r"-?\d+(?:\.\d+)?", txt)
    if not found:
        return None
    try:
        return float(found[0])
    except Exception:
        return None


def valid_lat_lon(lat, lon) -> bool:
    try:
        lat = float(lat)
        lon = float(lon)
        return -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0)
    except Exception:
        return False


def bearing_destination(lat: float, lon: float, bearing_deg: float, distance_m: float) -> Tuple[float, float]:
    """
    Calcula destino geográfico a partir de lat/lon, bearing y distancia.
    Regresa (lat, lon).
    """
    brng = math.radians(float(bearing_deg))
    lat1 = math.radians(float(lat))
    lon1 = math.radians(float(lon))
    dr = float(distance_m) / EARTH_RADIUS_M

    lat2 = math.asin(
        math.sin(lat1) * math.cos(dr)
        + math.cos(lat1) * math.sin(dr) * math.cos(brng)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brng) * math.sin(dr) * math.cos(lat1),
        math.cos(dr) - math.sin(lat1) * math.sin(lat2)
    )

    return math.degrees(lat2), ((math.degrees(lon2) + 540) % 360) - 180


def circle_coords(lat: float, lon: float, radius_m: float, steps: int = 72):
    """Coordenadas de círculo para polígonos KML en formato [(lon, lat), ...]."""
    coords = []
    for i in range(steps + 1):
        b = i * 360.0 / steps
        dlat, dlon = bearing_destination(lat, lon, b, radius_m)
        coords.append((dlon, dlat))
    return coords


def sector_coords(
    lat: float,
    lon: float,
    azimuth_deg: float,
    radius_m: float,
    aperture_deg: float = 30.0,
    steps: int = 24,
):
    """Coordenadas de sector/azimuth para polígono KML en formato [(lon, lat), ...]."""
    half = float(aperture_deg) / 2.0
    start = float(azimuth_deg) - half
    end = float(azimuth_deg) + half
    coords = [(lon, lat)]

    if steps < 2:
        steps = 2

    for i in range(steps + 1):
        b = start + (end - start) * i / steps
        dlat, dlon = bearing_destination(lat, lon, b, radius_m)
        coords.append((dlon, dlat))

    coords.append((lon, lat))
    return coords


def line_coords_from_df(df: pd.DataFrame, lat_col: str, lon_col: str):
    coords = []
    for _, row in df.iterrows():
        lat = to_float(row.get(lat_col))
        lon = to_float(row.get(lon_col))
        if valid_lat_lon(lat, lon):
            coords.append((float(lon), float(lat)))
    return coords


def normalize_datetime(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """Agrega columna __datetime usando Datetime o Fecha+Hora cuando existan."""
    out = df.copy()

    dt_col = mapping.get("datetime")
    fecha_col = mapping.get("fecha")
    hora_col = mapping.get("hora")

    if dt_col and dt_col in out.columns:
        raw = out[dt_col].astype(str)
        out["__datetime"] = pd.to_datetime(raw, errors="coerce", dayfirst=True)
    elif fecha_col and hora_col and fecha_col in out.columns and hora_col in out.columns:
        raw = out[fecha_col].astype(str).str.strip() + " " + out[hora_col].astype(str).str.strip()
        out["__datetime"] = pd.to_datetime(raw, errors="coerce", dayfirst=True)
    elif fecha_col and fecha_col in out.columns:
        out["__datetime"] = pd.to_datetime(out[fecha_col].astype(str), errors="coerce", dayfirst=True)
    else:
        out["__datetime"] = pd.NaT

    out["__date"] = out["__datetime"].dt.strftime("%Y-%m-%d")
    out["__time"] = out["__datetime"].dt.strftime("%H:%M:%S")
    out.loc[out["__datetime"].isna(), "__date"] = "SIN_FECHA"
    out.loc[out["__datetime"].isna(), "__time"] = ""

    return out


def normalize_event_type(value: object) -> str:
    txt = str(value or "").strip().upper()
    rep = {
        "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U",
        "\n": " ", "\r": " ",
    }
    for a, b in rep.items():
        txt = txt.replace(a, b)
    txt = re.sub(r"\s+", " ", txt)

    if "VOZ" in txt and ("ENT" in txt or "IN" in txt):
        return "VOZ ENTRANTE"
    if "VOZ" in txt and ("SAL" in txt or "OUT" in txt):
        return "VOZ SALIENTE"
    if "SMS" in txt or "MENSAJE" in txt:
        return "SMS"
    if "DATO" in txt or "DATA" in txt or "GPRS" in txt or "INTERNET" in txt:
        return "DATOS"
    if "TRANSFER" in txt:
        return "TRANSFER"
    if txt:
        return txt
    return "SIN TIPO"


def safe_text(value, default: str = "S/D") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    txt = str(value).strip()
    return txt if txt else default


def safe_filename(value: str, fallback: str = "sentinel_mapper_kmz_pro") -> str:
    txt = str(value or "").strip()
    if not txt:
        txt = fallback
    txt = re.sub(r"[^\w\-. ]+", "_", txt, flags=re.UNICODE)
    txt = re.sub(r"\s+", "_", txt).strip("_")
    return txt or fallback
