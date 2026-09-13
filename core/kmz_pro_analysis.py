# -*- coding: utf-8 -*-
"""
Análisis básico de eventos para Sentinel Mapper KMZ Pro.
"""

from __future__ import annotations

import pandas as pd

from .kmz_pro_utils import to_float, valid_lat_lon


def build_summary(df: pd.DataFrame, mapping: dict) -> dict:
    total = len(df)
    fechas = sorted([x for x in df.get("__date", pd.Series(dtype=str)).dropna().unique() if x != "SIN_FECHA"])
    tipos = df.get("__tipo", pd.Series(dtype=str)).value_counts().to_dict()

    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    mapeables = 0
    if lat_col and lon_col:
        for _, row in df.iterrows():
            if valid_lat_lon(to_float(row.get(lat_col)), to_float(row.get(lon_col))):
                mapeables += 1

    telefono_col = mapping.get("telefono")
    telefono = "S/D"
    if telefono_col and telefono_col in df.columns and not df[telefono_col].dropna().empty:
        telefono = str(df[telefono_col].dropna().iloc[0])

    resumen = {
        "Teléfono investigado": telefono,
        "Total registros": total,
        "Eventos mapeables": mapeables,
        "Rango de fechas": f"{fechas[0]} a {fechas[-1]}" if fechas else "S/D",
        "Días con actividad": len(fechas),
        "Tipos detectados": ", ".join([f"{k}: {v}" for k, v in tipos.items()]) if tipos else "S/D",
    }
    return resumen


def antenna_groups(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    az_col = mapping.get("azimuth")

    if not lat_col or not lon_col:
        return pd.DataFrame()

    work = df.copy()
    work["__lat"] = work[lat_col].apply(to_float)
    work["__lon"] = work[lon_col].apply(to_float)
    work["__az"] = work[az_col].apply(to_float) if az_col and az_col in work.columns else None
    work = work[work.apply(lambda r: valid_lat_lon(r["__lat"], r["__lon"]), axis=1)]
    if work.empty:
        return pd.DataFrame()

    # Redondeo para evitar duplicados por microvariaciones.
    work["__lat_key"] = work["__lat"].round(6)
    work["__lon_key"] = work["__lon"].round(6)
    work["__az_key"] = work["__az"].fillna(-1).round(0) if "__az" in work else -1

    rows = []
    group_cols = ["__lat_key", "__lon_key", "__az_key"]
    for idx, g in work.groupby(group_cols, dropna=False):
        types = g.get("__tipo", pd.Series(dtype=str)).value_counts()
        first_dt = g["__datetime"].min() if "__datetime" in g.columns else pd.NaT
        last_dt = g["__datetime"].max() if "__datetime" in g.columns else pd.NaT

        rows.append({
            "lat": float(g["__lat"].iloc[0]),
            "lon": float(g["__lon"].iloc[0]),
            "azimuth": None if float(g["__az_key"].iloc[0]) == -1 else float(g["__az_key"].iloc[0]),
            "total": len(g),
            "first": "" if pd.isna(first_dt) else str(first_dt),
            "last": "" if pd.isna(last_dt) else str(last_dt),
            "dominant_type": types.index[0] if not types.empty else "S/D",
        })

    return pd.DataFrame(rows).sort_values(["total"], ascending=False).reset_index(drop=True)


def relevant_events(df: pd.DataFrame, mapping: dict, max_night_events: int = 20) -> list:
    """
    Regresa lista de dicts:
    {"motivo": "...", "row": Series/dict}
    """
    out = []
    if df.empty:
        return out

    work = df.copy()
    if "__datetime" in work.columns:
        work = work.sort_values("__datetime")

    # Primer y último evento por día
    if "__date" in work.columns:
        for day, g in work.groupby("__date", dropna=False):
            if day == "SIN_FECHA" or g.empty:
                continue
            g2 = g.sort_values("__datetime") if "__datetime" in g.columns else g
            out.append({"motivo": f"Primer evento del día {day}", "row": g2.iloc[0].to_dict()})
            if len(g2) > 1:
                out.append({"motivo": f"Último evento del día {day}", "row": g2.iloc[-1].to_dict()})

    # Llamada o evento con mayor duración
    dur_col = mapping.get("duracion")
    if dur_col and dur_col in work.columns:
        dur = pd.to_numeric(work[dur_col], errors="coerce")
        if dur.notna().any():
            idx = dur.idxmax()
            out.append({"motivo": "Evento con mayor duración", "row": work.loc[idx].to_dict()})

    # Eventos nocturnos
    if "__datetime" in work.columns:
        night = work[work["__datetime"].dt.hour.isin([0, 1, 2, 3, 4, 5])]
        for _, row in night.head(max_night_events).iterrows():
            out.append({"motivo": "Evento nocturno 00:00-05:59", "row": row.to_dict()})

    # Quitar duplicados exactos por motivo + fecha/hora + coordenadas
    seen = set()
    clean = []
    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    for item in out:
        r = item["row"]
        key = (
            item["motivo"],
            str(r.get("__datetime", "")),
            str(r.get(lat_col, "")),
            str(r.get(lon_col, "")),
        )
        if key in seen:
            continue
        seen.add(key)
        clean.append(item)
    return clean
