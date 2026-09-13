# -*- coding: utf-8 -*-
# pages/app_mapper_azimuth.py — Go Mapper 2 · KMZ Azimut (estable, sin track)
# 01 — Tráfico global (ligero): antenas únicas → eventos (iconos/colores) + círculo + Wedges globales (Voz/SMS)
# 02 — Días específicos (detallado): por día → antenas con actividad → eventos del día + círculo + wedges (Voz/SMS)
# Cambios integrados:
# - SIN gx:Track y SIN timestamps (no hay animación ni líneas ligando puntos).
# - Resumen (popup) muestra Azimuth en cada evento de Voz/SMS: "Az 140° — 20:35:05 — SMS — 6681…→…".
# - Wedges (Az …°) muestran FECHA + HORA por evento y rango de fechas del grupo.
# - Overlay (brújula) se puede subir/URL fuera del form.

import os
import io
import re
import math
import zipfile
from typing import Dict, Tuple, Optional, List

import numpy as np
import pandas as pd
import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")
import simplekml
# --- GUARD DE ACCESO A LA SUITE ---
if not (st.session_state.get("logged_in", False) or st.session_state.get("suite_auth", False)):
    st.warning("Primero inicia sesión en la portada de Go Mapper Suite.")
    try:
        # Regresa a la portada principal
        st.switch_page("app.py")
    except Exception:
        # En versiones sin switch_page, al menos detiene la ejecución
        st.stop()
# --- FIN GUARD ---

# ────────────────────────── Configuración / Navegación ──────────────────────────
pass  # Page configuration is initialized before rendering.

AUTH_STRICT = os.getenv("GM_REQUIRE_LOGIN", "0") == "1"
AUTH_OK = bool(st.session_state.get("suite_auth", False)) or (os.getenv("BYPASS_SUBAPP_LOGIN", "0") == "1")
if AUTH_STRICT and not AUTH_OK:
    st.info("Acceso restringido: inicia sesión para usar este módulo.")
    try:
        st.page_link("app.py", label="🔐 Ir al Login")
    except Exception:
        pass
    st.stop()

from suite_nav import render_suite_sidebar
from ui.components import render_page_header
render_suite_sidebar()

# ─────────────────────────────── Constantes ───────────────────────────────
DEFAULT_RADIUS = 800
DEFAULT_APERTURE_DEG = 20  # por día
GLOBAL_APERTURE_DEG = 20   # global (puedes ajustar si quieres distinto)

# Íconos KML estándar
ICON_CIRCLE   = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
ICON_SQUARE   = "http://maps.google.com/mapfiles/kml/shapes/placemark_square.png"
ICON_TRIANGLE = "http://maps.google.com/mapfiles/kml/shapes/placemark_triangle.png"
ICON_DOT      = "http://maps.google.com/mapfiles/kml/shapes/target.png"  # para Datos

PRIMARY_PALETTE = {
    "Rojo": "#FF0000", "Azul": "#0066FF", "Verde": "#00C853", "Amarillo": "#FFD600",
    "Naranja": "#FF9100", "Morado": "#7E57C2", "Cian": "#00BCD4", "Rosa": "#E91E63",
    "Gris": "#9E9E9E", "Personalizado": None,
}

# ─────────────────────────────── Helpers ───────────────────────────────
def abgr(a: int, r: int, g: int, b: int) -> str:
    a = max(0, min(255, int(a))); r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g))); b = max(0, min(255, int(b)))
    return f"{a:02x}{b:02x}{g:02x}{r:02x}"

def hex_rgb_to_abgr(hex_rgb: str, alpha_255: int = 255) -> str:
    if not isinstance(hex_rgb, str) or not hex_rgb.startswith("#") or len(hex_rgb) != 7:
        rr, gg, bb = (255, 0, 0)
    else:
        rr = int(hex_rgb[1:3], 16); gg = int(hex_rgb[3:5], 16); bb = int(hex_rgb[5:7], 16)
    a = max(0, min(255, int(alpha_255)))
    return f"{a:02x}{bb:02x}{gg:02x}{rr:02x}"

def canon_tipo(v: str) -> Optional[str]:
    if v is None: return None
    s = str(v).strip().lower()
    if "voz" in s and "sal" in s: return "Voz Saliente"
    if "voz" in s and ("ent" in s or "entr" in s): return "Voz Entrante"
    if "sms" in s or "mensaje" in s: return "SMS"
    if "datos" in s or "data" in s: return "Datos"
    return s.title() if s else None

def meters_to_deg(lat: float, meters: float) -> Tuple[float, float]:
    lat = float(lat)
    dlat = meters / 111320.0
    dlon = meters / (111320.0 * max(0.1, math.cos(math.radians(lat))))
    return dlat, dlon

def construir_circulo(lat: float, lon: float, radius_m: float, npts: int = 72) -> List[Tuple[float, float]]:
    coords = []
    for b in np.linspace(0, 360, npts, endpoint=False):
        rad = math.radians(b)
        dlat, dlon = meters_to_deg(lat, radius_m)
        la = lat + dlat * math.sin(rad)
        lo = lon + dlon * math.cos(rad)
        coords.append((la, lo))
    coords.append(coords[0])
    return coords

def construir_sector(lat: float, lon: float, az_deg: float, radius_m: float, width_deg: float, npts: int = 36) -> List[Tuple[float, float]]:
    # 0° = Norte (lat +), 90° = Este (lon +)
    half = width_deg / 2.0
    bearings = np.linspace(az_deg - half, az_deg + half, npts)
    edge = []
    for b in bearings:
        rad = math.radians(b)
        dlat, dlon = meters_to_deg(lat, radius_m)
        la = lat + dlat * math.cos(rad)   # 0° → Norte
        lo = lon + dlon * math.sin(rad)   # 90° → Este
        edge.append((la, lo))
    return [(lat, lon)] + edge + [(lat, lon)]

def force_folder_check(folder, visible: bool = True, opened: bool = False):
    """Listas tipo 'check' (evitan radio)."""
    try: folder.liststyle.listitemtype = simplekml.ListItemType.check
    except Exception: pass
    try: folder.visibility = 1 if visible else 0
    except Exception: pass
    try: folder.open = 1 if opened else 0
    except Exception: pass
    return folder

def plus_activos(df: pd.DataFrame) -> set:
    base = df.dropna(subset=["Latitud","Longitud","PLUS_CODE"]).copy()
    return set(base["PLUS_CODE"].astype(str).unique().tolist())

# ───────────────────── Descripciones HTML (con separadores) ─────────────────────
PREF_LABELS = {
    "Tipo_norm": "Tipo", "FechaHora": "FechaHora", "Hora": "Hora",
    "Duración": "Duración", "Duracion": "Duración",
    "Número A": "Número A", "Numero A": "Número A", "Número B": "Número B", "Numero B": "Número B",
    "IMEI": "IMEI", "IMSI": "IMSI",
    "PLUS_CODE": "PLUS_CODE", "PLUS_CODE_NOMBRE": "PLUS_CODE_NOMBRE",
    "Latitud": "Latitud", "Longitud": "Longitud", "Azimuth_deg": "Azimuth (°)",
}
HIDE_COLS = set(["Tipo","Tipo_norm_cat"])

def _fmt_val(v, key):
    if pd.isna(v): return "—"
    if isinstance(v, float) and key in ("Latitud","Longitud"): return f"{v:.6f}"
    if isinstance(v, (pd.Timestamp, np.datetime64)):
        try: return pd.to_datetime(v).strftime("%Y-%m-%d %H:%M:%S")
        except Exception: return str(v)
    return str(v)

def _extract_azimuth_deg_from_row(ev: pd.Series) -> Optional[int]:
    """Devuelve el azimuth entero si existe (Azimuth_deg/Azimuth/Azimuth_raw)."""
    for key in ("Azimuth_deg", "Azimuth", "Azimuth_raw"):
        if key in ev.index and pd.notna(ev.get(key, None)):
            try:
                m = re.search(r"-?\d+(?:\.\d+)?", str(ev.get(key)))
                if m:
                    return int(round(float(m.group()))) % 360
            except Exception:
                continue
    return None

def descripcion_evento_html(ev: pd.Series) -> str:
    cols, seen = [], set()
    for k in PREF_LABELS.keys():
        if k in ev.index and k not in HIDE_COLS:
            cols.append(k); seen.add(k)
    for k in ev.index:
        if k in HIDE_COLS: continue
        if k not in seen: cols.append(k); seen.add(k)
    rows = []
    for k in cols:
        label = PREF_LABELS.get(k, k); val = _fmt_val(ev.get(k, None), k)
        rows.append(f"<tr><th style='text-align:left;padding:2px 6px'>{label}</th><td style='padding:2px 6px'>{val}</td></tr>")
    return "<![CDATA[<div style='font-family:Inter,Segoe UI,Arial;font-size:12px'><table border='0' cellspacing='0' cellpadding='0'>" + "".join(rows) + "</table></div>]]>"

def resumen_eventos_html(df_ant: pd.DataFrame, max_items: int = 200) -> str:
    """Resumen para Antena / Antena (día) con separadores y azimuth (si Voz/SMS)."""
    sub = df_ant.dropna(subset=["FechaHora"]).sort_values("FechaHora")
    counts = sub["Tipo_norm"].fillna("—").value_counts().to_dict()
    counts_s = " · ".join([f"{k}: {v}" for k, v in counts.items()]) or "Sin actividad"

    rows = []
    for _, ev in sub.head(max_items).iterrows():
        # Hora
        try:
            h = pd.to_datetime(ev.get("FechaHora")).strftime("%H:%M:%S")
        except Exception:
            h = str(ev.get("Hora", "")).strip() or "—"

        # Tipo y números
        t = str(ev.get("Tipo_norm", "—"))
        a = (ev.get("Número A") or ev.get("Numero A") or "")
        b = (ev.get("Número B") or ev.get("Numero B") or "")
        who = ""
        if t.lower().startswith("voz"):
            who = f" — {a}→{b}" if (a or b) else ""
        elif t.lower() == "sms":
            who = f" — SMS {a}→{b}" if (a or b) else " — SMS"

        # Azimuth solo para Voz/SMS (si existe)
        az_txt = ""
        if t in ("Voz Entrante", "Voz Saliente", "SMS"):
            az = _extract_azimuth_deg_from_row(ev)
            if az is not None:
                az_txt = f"Az {az}° — "

        rows.append(
            f"<div style='border-top:1px dashed #bbb;margin:4px 0;padding-top:4px'>"
            f"{az_txt}{h} — {t}{who}</div>"
        )

    items = "".join(rows) if rows else "—"
    return (
        "<![CDATA[<div style='font-family:Inter,Segoe UI,Arial;font-size:12px'>"
        f"<b>Actividad:</b> {counts_s}<br/>{items}</div>]]>"
    )

def descripcion_wedge_group_html(g: pd.DataFrame, az: float, max_items: int = 200) -> str:
    """
    Popup para un grupo (wedge) de azimut: incluye FECHA + HORA por evento y rango de fechas.
    Formato por línea:
      2025-01-05 · 15:33:23 — Voz Saliente — 6681017612→6682290094
    """
    g = g.dropna(subset=["FechaHora"]).sort_values("FechaHora")
    n = len(g)
    counts = g["Tipo_norm"].fillna("—").value_counts().to_dict()
    counts_s = " · ".join([f"{k}: {v}" for k, v in counts.items()]) or "—"

    # Rango de fechas (por si hay eventos de varios días en el wedge global)
    try:
        tmin = pd.to_datetime(g["FechaHora"]).min()
        tmax = pd.to_datetime(g["FechaHora"]).max()
        if pd.isna(tmin) or pd.isna(tmax):
            date_range = "—"
        else:
            dmin = tmin.strftime("%Y-%m-%d")
            dmax = tmax.strftime("%Y-%m-%d")
            date_range = dmin if dmin == dmax else f"{dmin} → {dmax}"
    except Exception:
        date_range = "—"

    rows = []
    for _, ev in g.head(max_items).iterrows():
        # Fecha y hora
        try:
            ts = pd.to_datetime(ev.get("FechaHora"))
            d = ts.strftime("%Y-%m-%d")
            h = ts.strftime("%H:%M:%S")
        except Exception:
            d = str(ev.get("Fecha", "")).strip() or "—"
            h = str(ev.get("Hora", "")).strip() or "—"

        # Tipo y números
        t = str(ev.get("Tipo_norm","—"))
        a = (ev.get("Número A") or ev.get("Numero A") or "")
        b = (ev.get("Número B") or ev.get("Numero B") or "")
        who = ""
        if t.lower().startswith("voz"):
            who = f" — {a}→{b}" if (a or b) else ""
        elif t.lower() == "sms":
            who = f" — SMS {a}→{b}" if (a or b) else " — SMS"

        rows.append(
            f"<div style='border-top:1px dashed #bbb;margin:4px 0;padding-top:4px'>"
            f"{d} · {h} — {t}{who}</div>"
        )

    lines = "".join(rows) if rows else "—"
    header = f"<b>Az {int(az)}°</b> — {n} evento(s) · {counts_s}<br/><i>Fechas: {date_range}</i>"
    return f"<![CDATA[<div style='font-family:Inter,Segoe UI,Arial;font-size:12px'>{header}<br/>{lines}</div>]]>"

# ─────────────────────────────── Estilos ───────────────────────────────
def estilo_circulo(fill_abgr_v: str, line_abgr_v: str, line_w: int = 1) -> simplekml.Style:
    stl = simplekml.Style()
    stl.polystyle.color = fill_abgr_v
    stl.linestyle.color = line_abgr_v
    stl.linestyle.width = int(line_w)
    return stl

def estilo_sector(fill_abgr_v: str, line_abgr_v: str, line_w: int = 2) -> simplekml.Style:
    stl = simplekml.Style()
    stl.polystyle.color = fill_abgr_v
    stl.linestyle.color = line_abgr_v
    stl.linestyle.width = int(line_w)
    return stl

def estilo_antena(hide_label: bool, label_scale: float, label_alpha: int,
                  icon_href: Optional[str], icon_scale: float) -> simplekml.Style:
    stl = simplekml.Style()
    if icon_href:
        stl.iconstyle.icon.href = icon_href
        stl.iconstyle.scale = float(icon_scale)
        stl.iconstyle.color = abgr(255, 255, 255, 255)
    else:
        stl.iconstyle.scale = float(max(0.8, icon_scale))
        stl.iconstyle.color = abgr(255, 170, 170, 170)
    stl.labelstyle.scale = 0.0 if hide_label else float(label_scale)
    stl.labelstyle.color = abgr(int(label_alpha), 255, 255, 255)
    return stl

def estilos_eventos(icon_scale: float = 0.95, ocultar_eventos: bool = False) -> Dict[str, simplekml.Style]:
    cfg = {
        "Voz Entrante": (ICON_CIRCLE,   "#00C853"),
        "Voz Saliente": (ICON_SQUARE,   "#FF9100"),
        "SMS":          (ICON_TRIANGLE, "#E040FB"),
        "Datos":        (ICON_DOT,      "#1E88E5"),
        "Otro":         (ICON_CIRCLE,   "#9E9E9E"),
    }
    styles = {}
    for tipo, (href, hx) in cfg.items():
        stl = simplekml.Style()
        stl.iconstyle.icon.href = href
        stl.iconstyle.color = hex_rgb_to_abgr(hx, 255)
        stl.iconstyle.scale = float(icon_scale)
        stl.labelstyle.scale = 0.0 if ocultar_eventos else 0.6
        stl.labelstyle.color = abgr(255, 255, 255, 255)
        styles[tipo] = stl
    return styles

# ─────────────────────────────── Lectura/normalización ───────────────────────────────
@st.cache_data(show_spinner=False)
def read_clean_excel(file) -> pd.DataFrame:
    xls = pd.ExcelFile(file)
    sheet = "Datos_Limpios" if "Datos_Limpios" in xls.sheet_names else xls.sheet_names[0]
    return pd.read_excel(xls, sheet_name=sheet)

def cast_str(s) -> pd.Series:
    return s.astype("string").str.strip()

@st.cache_data(show_spinner=False)
def build_datetime(df_in: pd.DataFrame) -> pd.DataFrame:
    from core.datetime_utils import parse_local_datetime
    df = df_in.copy()
    dt = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    for col in ["FechaHora", "Datetime", "fecha_hora", "Fecha y hora", "timestamp"]:
        if col in df:
            dt = dt.fillna(df[col].map(parse_local_datetime))
    fcol = next((c for c in ["Fecha de la comunicación", "Fecha", "DATE", "fecha"] if c in df), None)
    hcol = next((c for c in ["Hora de la comunicación", "Hora", "TIME", "hora"] if c in df), None)
    if fcol:
        fallback = pd.Series([parse_local_datetime(row[fcol], row.get(hcol)) for _,row in df.iterrows()],index=df.index,dtype="datetime64[ns]")
        dt = dt.fillna(fallback)
    df["FechaHora"] = dt
    df["Fecha_dia"] = dt.dt.date.astype("string")
    return df

@st.cache_data(show_spinner=False)
def coerce_azimuth_deg(df_in: pd.DataFrame) -> pd.DataFrame:
    df = df_in.copy()
    def _to_deg(val):
        if pd.isna(val): return np.nan
        m = re.search(r"-?\d+(?:\.\d+)?", str(val))
        return float(m.group()) if m else np.nan
    if "Azimuth_deg" not in df.columns:
        df["Azimuth_deg"] = np.nan
    if df["Azimuth_deg"].isna().all() and "Azimuth" in df.columns:
        df["Azimuth_deg"] = df["Azimuth"].apply(_to_deg)
    if "Azimuth_raw" in df.columns:
        df["Azimuth_deg"] = df["Azimuth_deg"].fillna(df["Azimuth_raw"].apply(_to_deg))
    df.loc[(df["Azimuth_deg"] < 0) | (df["Azimuth_deg"] >= 360), "Azimuth_deg"] = np.nan
    df["Azimuth_deg"] = df["Azimuth_deg"].round(0)
    return df

@st.cache_data(show_spinner=False)
def extract_phone_for_name(df: pd.DataFrame) -> str:
    candidates = ["Teléfono","Telefono","MSISDN","Número A","Numero A","A","Número Origen","Numero Origen"]
    series = []
    for c in candidates:
        if c in df.columns:
            s = df[c].astype(str).str.replace(r"\D+","",regex=True)
            s = s[s.str.len() >= 8]
            if not s.empty: series.append(s)
    if not series: return "SIN_TELEFONO"
    s_all = pd.concat(series, ignore_index=True)
    vc = s_all.value_counts(dropna=True)
    return str(vc.index[0]) if not vc.empty else "SIN_TELEFONO"

@st.cache_data(show_spinner=False)
def antenas_repr(df: pd.DataFrame) -> pd.DataFrame:
    need = ["PLUS_CODE","Latitud","Longitud"]
    for c in need:
        if c not in df.columns:
            return pd.DataFrame(columns=["PLUS_CODE","Latitud","Longitud","NombreAntena"])
    d = df.dropna(subset=need).copy()
    if "PLUS_CODE_NOMBRE" in d.columns:
        d["NombreAntena"] = d["PLUS_CODE_NOMBRE"].astype(str).replace({"": "Antena"})
    else:
        d["NombreAntena"] = d["PLUS_CODE"].astype(str)
    rep = (d.groupby(["PLUS_CODE"], observed=False)
             .agg(Latitud=("Latitud","first"),
                  Longitud=("Longitud","first"),
                  NombreAntena=("NombreAntena","first"))
             .reset_index())
    return rep

def _sanitize_for_fname(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]+","_", s)
    s = re.sub(r"\s+"," ", s).strip()
    return s or "Escenario"

# ─────────────────────────────── Generador KMZ ───────────────────────────────
def generar_kmz(
    df, tipos, radio_unico, apertura,
    escenario_name,
    hide_antenna_label, antena_label_scale, antena_label_alpha,
    overlay_url, overlay_alpha, overlay_scale, overlay_rotation,
    overlay_force_north, overlay_flip_180,
    antenna_icon_href, antenna_icon_bytes, antenna_icon_scale,
    circle_hex, circle_alpha, azimut_hex, line_w,
    event_icon_scale,
    overlay_href: Optional[str] = None, overlay_bytes: Optional[bytes] = None,
    limit_events_per_antenna: int = 400
):
    kml = simplekml.Kml(name=escenario_name or "KMZ")

    ant_df_all = antenas_repr(df)
    ant_index_all = (ant_df_all.drop_duplicates("PLUS_CODE")
                              .set_index("PLUS_CODE")[["Latitud","Longitud","NombreAntena"]]
                              .to_dict("index")) if not ant_df_all.empty else {}

    st_evt = estilos_eventos(icon_scale=float(event_icon_scale), ocultar_eventos=False)
    st_ant = estilo_antena(hide_antenna_label, antena_label_scale, antena_label_alpha,
                           antenna_icon_href, antenna_icon_scale)

    circ_style = estilo_circulo(
        fill_abgr_v=hex_rgb_to_abgr(circle_hex, circle_alpha),
        line_abgr_v=hex_rgb_to_abgr(circle_hex, min(circle_alpha+100, 255)),
        line_w=int(line_w)
    )
    st_evt_wedge = estilo_sector(
        fill_abgr_v=hex_rgb_to_abgr(azimut_hex, 70),
        line_abgr_v=hex_rgb_to_abgr(azimut_hex, 220),
        line_w=max(1, int(line_w))
    )

    root = kml.newfolder(name=escenario_name or "Escenario")
    force_folder_check(root, visible=True, opened=True)

    # ───────────── 01 — Tráfico global (ligero) ─────────────
    f_global = root.newfolder(name="01 — Tráfico global (ligero)")
    force_folder_check(f_global, visible=True, opened=True)

    for plus, info in ant_index_all.items():
        lat0, lon0 = float(info["Latitud"]), float(info["Longitud"])
        name_ant = str(info.get("NombreAntena","Antena"))

        f_ant = f_global.newfolder(name=f"📡 {name_ant} ({plus})")
        force_folder_check(f_ant, visible=True, opened=False)

        # Punto + resumen (todos los eventos de esa antena)
        df_ant_all = df[df["PLUS_CODE"].astype(str) == str(plus)].copy()
        p = f_ant.newpoint(name="", coords=[(lon0, lat0, 30.0)])
        p.altitudemode = simplekml.AltitudeMode.relativetoground
        p.style = st_ant
        p.description = f"<b>Antena</b><br>PLUS_CODE: {plus}<br>Nombre: {name_ant}<br>Ubicación: {lat0:.6f}, {lon0:.6f}<hr/>" + \
                        resumen_eventos_html(df_ant_all, max_items=limit_events_per_antenna)

        # Círculo global
        circ_coords = construir_circulo(lat0, lon0, float(radio_unico))
        polyc = f_ant.newpolygon(name="Cobertura (círculo)")
        polyc.outerboundaryis = [(lo, la) for la, lo in circ_coords]
        polyc.style = circ_style

        # Eventos (todos los días) con íconos/colores
        f_ev = f_ant.newfolder(name="Eventos")
        force_folder_check(f_ev, visible=True, opened=False)
        for tipo in ["Voz Entrante","Voz Saliente","SMS","Datos","Otro"]:
            g = df_ant_all[df_ant_all["Tipo_norm"] == tipo].sort_values("FechaHora")
            if g.empty: continue
            if limit_events_per_antenna and len(g) > limit_events_per_antenna:
                g = g.head(limit_events_per_antenna)
            f_t = f_ev.newfolder(name=tipo)
            force_folder_check(f_t, visible=True, opened=False)
            for _, ev in g.iterrows():
                try: lat, lon = float(ev["Latitud"]), float(ev["Longitud"])
                except Exception: continue
                try:
                    fh = ev.get("FechaHora", pd.NaT)
                    hora_txt = pd.to_datetime(fh).strftime("%H:%M:%S") if pd.notna(fh) else (str(ev.get("Hora","")).strip() or "—")
                except Exception:
                    hora_txt = str(ev.get("Hora","")).strip() or "—"
                p2 = f_t.newpoint(name=hora_txt, coords=[(lon, lat, 0)])
                p2.altitudemode = simplekml.AltitudeMode.clamptoground
                p2.style = st_evt.get(tipo, st_evt["Otro"])
                p2.description = descripcion_evento_html(ev)
                # SIN timestamp (para evitar cualquier animación/track)

        # Wedges (global) SOLO Voz/SMS con azimuth
        g_vs = df_ant_all[(df_ant_all["Tipo_norm"].isin(["Voz Entrante","Voz Saliente","SMS"])) &
                          (~df_ant_all["Azimuth_deg"].isna())]
        if not g_vs.empty:
            f_wg = f_ant.newfolder(name="Wedges (global)")
            force_folder_check(f_wg, visible=True, opened=False)
            for az, g_az in g_vs.groupby("Azimuth_deg"):
                azf = float(az) % 360.0
                coords = construir_sector(lat0, lon0, azf, float(radio_unico), float(GLOBAL_APERTURE_DEG))
                poly = f_wg.newpolygon(name=f"Az {int(azf)}° ({len(g_az)} ev.)")
                poly.outerboundaryis = [(lo, la) for la, lo in coords]
                poly.style = st_evt_wedge
                poly.description = descripcion_wedge_group_html(g_az, azf)

    # ───────────── 02 — Días específicos (detallado) ─────────────
    f_days = root.newfolder(name="02 — Días específicos (detallado)")
    force_folder_check(f_days, visible=False, opened=False)  # desmarcada por defecto

    for fecha_dia, df_dia in df.groupby("Fecha_dia", sort=True):
        plus_day = plus_activos(df_dia)
        if not plus_day:
            continue

        f_d = f_days.newfolder(name=str(fecha_dia))
        force_folder_check(f_d, visible=True, opened=False)

        # Overlays del día (si configuraste overlay)
        f_ov = None
        if overlay_url or overlay_href or overlay_bytes:
            f_ov = f_d.newfolder(name="Overlays (brújula)")
            force_folder_check(f_ov, visible=True, opened=False)

        for plus in sorted(plus_day):
            info = ant_index_all.get(str(plus))
            if not info: continue
            lat0, lon0 = float(info["Latitud"]), float(info["Longitud"])
            name_ant = str(info.get("NombreAntena","Antena"))

            f_ant_d = f_d.newfolder(name=f"📡 {name_ant} ({plus})")
            force_folder_check(f_ant_d, visible=True, opened=False)

            # Punto + resumen del día
            df_ant_day = df_dia[df_dia["PLUS_CODE"].astype(str) == str(plus)].copy()
            p = f_ant_d.newpoint(name="", coords=[(lon0, lat0, 30.0)])
            p.altitudemode = simplekml.AltitudeMode.relativetoground
            p.style = st_ant
            p.description = f"<b>Antena (día)</b><br>PLUS_CODE: {plus}<br>Nombre: {name_ant}<br>Ubicación: {lat0:.6f}, {lon0:.6f}<hr/>" + \
                            resumen_eventos_html(df_ant_day)

            # Eventos del día
            f_ev = f_ant_d.newfolder(name="Eventos (día)")
            force_folder_check(f_ev, visible=True, opened=False)
            for tipo in ["Voz Entrante","Voz Saliente","SMS","Datos","Otro"]:
                g = df_ant_day[df_ant_day["Tipo_norm"] == tipo].sort_values("FechaHora")
                if g.empty: continue
                f_t = f_ev.newfolder(name=tipo)
                force_folder_check(f_t, visible=True, opened=False)
                for _, ev in g.iterrows():
                    try: lat, lon = float(ev["Latitud"]), float(ev["Longitud"])
                    except Exception: continue
                    try:
                        fh = ev.get("FechaHora", pd.NaT)
                        hora_txt = pd.to_datetime(fh).strftime("%H:%M:%S") if pd.notna(fh) else (str(ev.get("Hora","")).strip() or "—")
                    except Exception:
                        hora_txt = str(ev.get("Hora","")).strip() or "—"
                    p2 = f_t.newpoint(name=hora_txt, coords=[(lon, lat, 0)])
                    p2.altitudemode = simplekml.AltitudeMode.clamptoground
                    p2.style = st_evt.get(tipo, st_evt["Otro"])
                    p2.description = descripcion_evento_html(ev)
                    # SIN timestamp

            # Círculo (siempre)
            circ_coords = construir_circulo(lat0, lon0, float(radio_unico))
            polyc = f_ant_d.newpolygon(name="Cobertura (círculo)")
            polyc.outerboundaryis = [(lo, la) for la, lo in circ_coords]
            polyc.style = circ_style

            # Wedges SOLO para Voz/SMS (si hay azimuth)
            g_vs = df_ant_day[(df_ant_day["Tipo_norm"].isin(["Voz Entrante","Voz Saliente","SMS"])) &
                              (~df_ant_day["Azimuth_deg"].isna())]
            if not g_vs.empty:
                f_w = f_ant_d.newfolder(name="Wedges (Voz/SMS)")
                force_folder_check(f_w, visible=True, opened=False)
                for az, g_az in g_vs.groupby("Azimuth_deg"):
                    azf = float(az) % 360.0
                    coords = construir_sector(lat0, lon0, azf, float(radio_unico), float(apertura))
                    poly = f_w.newpolygon(name=f"Az {int(azf)}° ({len(g_az)} ev.)")
                    poly.outerboundaryis = [(lo, la) for la, lo in coords]
                    poly.style = st_evt_wedge
                    poly.description = descripcion_wedge_group_html(g_az, azf)

            # Overlay por antena del día (opcional)
            if f_ov is not None:
                half_m = float(radio_unico) * float(overlay_scale)
                dlat, dlon = meters_to_deg(lat0, half_m)
                ov = f_ov.newgroundoverlay(name=f"Brújula {name_ant}")
                ov.icon.href = overlay_url or overlay_href
                ov.color = abgr(int(overlay_alpha), 255, 255, 255)
                ov.latlonbox.north, ov.latlonbox.south = lat0 + dlat, lat0 - dlat
                ov.latlonbox.east,  ov.latlonbox.west  = lon0 + dlon, lon0 - dlon
                if not g_vs.empty:
                    az_mode = float(g_vs["Azimuth_deg"].mode().iloc[0]) % 360.0
                    rot = (az_mode + float(overlay_rotation)) % 360.0
                    if overlay_flip_180: rot = (rot + 180.0) % 360.0
                    ov.latlonbox.rotation = 0.0 if overlay_force_north else rot
                else:
                    ov.latlonbox.rotation = 0.0  # norte

    # Empaquetado KMZ
    from core.kml_visibility import hidden_kml
    kml_bytes = hidden_kml(kml.kml().encode("utf-8"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml_bytes)
        if antenna_icon_bytes and antenna_icon_href and not str(antenna_icon_href).lower().startswith(("http://","https://")):
            zf.writestr(antenna_icon_href, antenna_icon_bytes)
        if overlay_bytes and overlay_href and not str(overlay_href).lower().startswith(("http://","https://")):
            zf.writestr(overlay_href, overlay_bytes)
    return buf.getvalue()

# ─────────────────────────────── UI ───────────────────────────────
def main():
    render_page_header("KMZ Azimut", "Exporta antenas y sectores. Google Earth abre el árbol sin capas seleccionadas.", tags=["KMZ normal", "Capas apagadas"])
    st.caption("01 Global con iconos/colores + wedges (Voz/SMS). 02 Días específicos detallado. Sin gx:Track ni timestamps.")

    up = st.file_uploader("Carga tu archivo limpio (Excel)", type=["xlsx","xls"])
    if not up:
        st.info("Sube el Excel (hoja 'Datos_Limpios' preferida).")
        return

    try:
        df = read_clean_excel(up)
    except Exception as e:
        st.error(f"No se pudo leer el Excel: {e}")
        return

    # Tipos / coordenadas
    if "Latitud" in df.columns:  df["Latitud"]  = pd.to_numeric(df["Latitud"], errors="coerce").astype("float32")
    if "Longitud" in df.columns: df["Longitud"] = pd.to_numeric(df["Longitud"], errors="coerce").astype("float32")
    if "Tipo" in df.columns:     df["Tipo"]     = df["Tipo"].astype("string")
    if "PLUS_CODE" in df.columns:df["PLUS_CODE"]= df["PLUS_CODE"].astype("string")

    df = build_datetime(df)
    df = coerce_azimuth_deg(df)
    df["Tipo_norm"] = (df["Tipo"].apply(canon_tipo) if "Tipo" in df.columns else df.get("Tipo_norm", np.nan))

    telefono_pred = extract_phone_for_name(df)
    default_name = _sanitize_for_fname(f"{telefono_pred}_GoMapper_KMZ_Azimuth")

    # Métricas
    c0,c1,c2,c3 = st.columns(4)
    c0.metric("Filas", len(df))
    c1.metric("Coordenadas", int(df[["Latitud","Longitud"]].dropna().shape[0]))
    c2.metric("Azimuth válidos", int(df["Azimuth_deg"].notna().sum()))
    try:
        c3.metric("Rango", f"{pd.to_datetime(df['FechaHora']).min().date()} → {pd.to_datetime(df['FechaHora']).max().date()}")
    except Exception:
        c3.metric("Rango", "—")

    st.divider()

    # Overlay fuera del form
    st.subheader("🧭 Overlay (brújula) — subir PNG/URL sin aplicar")
    ov_c1, ov_c2 = st.columns([1,2])
    with ov_c1:
        overlay_mode = st.radio("Overlay de grados", ["Ninguno","URL http(s)","Subir PNG"],
                                horizontal=True, key="overlay_mode_global")
    with ov_c2:
        if overlay_mode == "URL http(s)":
            st.session_state["overlay_url"] = st.text_input("URL del PNG (con transparencia)",
                                                            value=st.session_state.get("overlay_url",""))
        elif overlay_mode == "Subir PNG":
            up_ov = st.file_uploader("Sube PNG de overlay", type=["png"], key="overlay_png_outside")
            if up_ov:
                st.session_state["overlay_png_bytes"] = up_ov.getvalue()
                st.session_state["overlay_png_name"]  = re.sub(r"[^A-Za-z0-9_.-]+","_", up_ov.name or "overlay.png")
                st.image(st.session_state["overlay_png_bytes"], caption="Previa de la brújula", width=120)

    st.divider()

    with st.form("param_form", clear_on_submit=False):
        st.subheader("⚙️ Cobertura / Azimut")
        colA, colB, colC, colD = st.columns(4)
        with colA:
            radio_unico = st.number_input("Radio cobertura (m)", 50, 15000, DEFAULT_RADIUS, 50)
            apertura = st.slider("Apertura WEDGE (°) (por día)", 5, 120, DEFAULT_APERTURE_DEG, 1)
        with colB:
            az_color_pick = st.selectbox("Color de AZIMUT", list(PRIMARY_PALETTE.keys()), index=1)
            azimut_hex = st.color_picker("Color personalizado", value="#00AAFF",
                                         disabled=(PRIMARY_PALETTE[az_color_pick] is not None))
            if PRIMARY_PALETTE[az_color_pick]: azimut_hex = PRIMARY_PALETTE[az_color_pick]
        with colC:
            circle_hex = st.color_picker("Color del círculo", value="#9E9E9E")
            circle_alpha = st.slider("Opacidad círculo (0-255)", 0, 255, 40, 5)
        with colD:
            line_w = st.slider("Grosor borde coberturas", 1, 6, 2, 1)

        st.subheader("🖊️ Eventos y filtros")
        colE, colF, colG = st.columns(3)
        with colE:
            tipos_unicos = sorted([t for t in df["Tipo_norm"].dropna().unique().tolist() if t])
            tipos = st.multiselect("Tipos a incluir", tipos_unicos, default=tipos_unicos)
        with colF:
            event_icon_scale = st.slider("Tamaño icono eventos", 0.4, 2.0, 0.95, 0.05)
            limit_events = st.number_input("Límite de eventos por antena (global)", 50, 2000, 400, 50)
        with colG:
            hide_antenna_label = st.checkbox("Ocultar etiqueta de antena", value=True)
            antena_label_scale = st.slider("Tamaño etiqueta", 0.2, 2.0, 0.8, 0.1, disabled=hide_antenna_label)
            antena_label_alpha = st.slider("Opacidad etiqueta (0-255)", 0, 255, 0 if hide_antenna_label else 220, 5)

        st.subheader("📡 Icono de antena")
        colI, colJ = st.columns(2)
        with colI:
            up_ant = st.file_uploader("Icono antena (PNG)", type=["png"], key="ant_png")
            if up_ant is not None:
                st.session_state["ant_png_bytes"] = up_ant.getvalue()
                st.session_state["ant_png_name"]  = "antenna.png"
        with colJ:
            antenna_icon_scale = st.slider("Escala icono antena", 0.5, 3.0, 1.0, 0.1)

        st.subheader("🧭 Parámetros de overlay (brújula)")
        colK, colL = st.columns(2)
        with colK:
            overlay_alpha = st.slider("Opacidad overlay (0-255)", 0, 255, 160, 5)
            overlay_scale = st.number_input("Escala overlay (1.0 = igual al radio)", 0.2, 3.0, 1.0, 0.1)
        with colL:
            overlay_rotation = st.slider("Ajuste adicional (°)", -180, 180, 0, 1)
            overlay_force_north = st.checkbox("Forzar norte (sin azimuth)", value=True)
            overlay_flip_180 = st.checkbox("Corregir 180°", value=False)

        escenario_name = st.text_input("Nombre del escenario (carpeta raíz)", value=default_name)
        aplicado = st.form_submit_button("✅ Aplicar parámetros")
        if aplicado:
            st.session_state["param_ok"] = True

    st.divider()

    colX, colY = st.columns([1,1])
    with colX:
        if st.button("🚀 Generar KMZ", disabled=not st.session_state.get("param_ok", True)):
            # Overlay elegido fuera del form
            overlay_mode_curr = st.session_state.get("overlay_mode_global","Ninguno")
            overlay_url_use, overlay_bytes_use, overlay_href_use = "", None, None
            if overlay_mode_curr == "URL http(s)":
                overlay_url_use = st.session_state.get("overlay_url","").strip()
            elif overlay_mode_curr == "Subir PNG":
                overlay_bytes_use = st.session_state.get("overlay_png_bytes", None)
                overlay_href_use  = st.session_state.get("overlay_png_name", "overlay.png")

            # Icono antena
            if "ant_png_bytes" in st.session_state:
                antenna_icon_bytes = st.session_state["ant_png_bytes"]
                antenna_icon_href = st.session_state.get("ant_png_name", "antenna.png")
            else:
                antenna_icon_bytes = None; antenna_icon_href = None

            kmz_bytes = generar_kmz(
                df=df[df["Tipo_norm"].isin(tipos)] if tipos else df,
                tipos=tipos, radio_unico=int(radio_unico), apertura=int(apertura),
                escenario_name=escenario_name,
                hide_antenna_label=bool(hide_antenna_label), antena_label_scale=float(antena_label_scale),
                antena_label_alpha=int(antena_label_alpha),
                overlay_url=overlay_url_use, overlay_alpha=int(overlay_alpha),
                overlay_scale=float(overlay_scale), overlay_rotation=float(overlay_rotation),
                overlay_force_north=bool(overlay_force_north), overlay_flip_180=bool(overlay_flip_180),
                antenna_icon_href=antenna_icon_href, antenna_icon_bytes=antenna_icon_bytes,
                antenna_icon_scale=float(antenna_icon_scale),
                circle_hex=circle_hex, circle_alpha=int(circle_alpha),
                azimut_hex=azimut_hex, line_w=int(line_w),
                event_icon_scale=float(event_icon_scale),
                overlay_href=overlay_href_use, overlay_bytes=overlay_bytes_use,
                limit_events_per_antenna=int(limit_events),
            )
            if kmz_bytes:
                st.session_state["KMZ_BYTES"] = kmz_bytes
                st.success("KMZ generado (sin track).")
            else:
                st.warning("No fue posible generar el KMZ (revisa coordenadas/fechas).")

    with colY:
        if "KMZ_BYTES" in st.session_state and st.session_state["KMZ_BYTES"]:
            st.download_button(
                "⬇️ Descargar KMZ",
                data=st.session_state["KMZ_BYTES"],
                file_name=f"{_sanitize_for_fname(escenario_name)}.kmz",
                mime="application/vnd.google-earth.kmz",
            )
        else:
            st.caption("Genera el KMZ para habilitar la descarga.")

if __name__ == "__main__":
    main()
