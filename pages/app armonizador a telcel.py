# pages/02_Compilador_Telcel_11col.py
# -*- coding: utf-8 -*-
import io
import re
import json
import math
import unicodedata
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")

from suite_nav import render_suite_sidebar  # ← menú de la suite

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

# --- MENÚ LATERAL DE LA SUITE (sin opciones del compilador) ---
render_suite_sidebar()

# ---------------------------------------------------------------------
# Evitar conflicto con otras páginas al configurar la página
# ---------------------------------------------------------------------
if "page_configured_compilador_telcel" not in st.session_state:
    try:
        pass  # Page configuration is initialized before rendering.
    except Exception:
        pass
    st.session_state["page_configured_compilador_telcel"] = True

APP_TITLE = "Compilador Único → TELCEL_CRUDO (11 columnas)"
TARGET_COLUMNS = [
    "Telefono", "Tipo", "Numero A", "Numero B", "Fecha", "Hora",
    "Durac. Seg.", "IMEI", "LATITUD", "LONGITUD", "Azimuth"
]

# =============================================================================
# UTILIDADES TEXTO
# =============================================================================
def strip_accents(s: str) -> str:
    if not isinstance(s, str):
        s = str(s)
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def norm(s: str) -> str:
    s = strip_accents(s or "").lower().strip()
    s = re.sub(r"[\s\-\._/]+", " ", s)
    return s

# =============================================================================
# SINÓNIMOS / ALIAS DE COLUMNAS
# =============================================================================
SYNONYMS: Dict[str, List[str]] = {
    "Telefono": [
        "telefono", "teléfono", "msisdn", "linea", "línea", "subscriber", "abonado",
        "phone", "num subs", "numero de linea", "numero", "account msisdn"
    ],
    "Tipo": [
        "tipo", "service type", "call type", "evento", "registro", "cdr type", "bearer",
        "clase", "servicio", "trafico", "tráfico", "usage type", "serv"
    ],
    "Dirección (ENT/SAL)": [
        "t_reg", "t reg", "sentido", "entrada/salida", "in/out", "direccion", "direction", "dir",
        "sentido llamada", "entrada", "salida", "ent", "sal"
    ],
    "Numero A": [
        "numero a", "a", "origen", "calling", "caller", "calling number", "originating",
        "ani", "calling party", "msc origin", "numero origen", "num a", "from", "source",
        "num_a", "a_party"
    ],
    "Numero B": [
        "numero b", "b", "destino", "called", "callee", "b-party", "terminating",
        "called number", "numero destino", "num b", "to", "target", "destination",
        "dest", "b_party"
    ],
    "Fecha": [
        "fecha", "date", "start date", "call date", "fecha de la comunicacion",
        "event date", "fecha inicio", "dia", "day", "start_datetime", "start time"
    ],
    "Hora": [
        "hora", "time", "start time (time)", "call time", "timestamp", "hora de la comunicacion",
        "hora inicio", "time of day"
    ],
    "Durac. Seg.": [
        "durac seg", "duracion", "duración", "duration", "duration ms", "duration sec",
        "call duration", "tiempo", "dur", "duracion s", "dur ms", "dur sec", "durac seg."
    ],
    "IMEI": ["imei", "imeisv", "equipo", "device id", "handset", "terminal id", "num_a_imei"],
    "LATITUD": ["latitud", "lat", "latitude", "y", "coord y", "lat dms"],
    "LONGITUD": ["longitud", "lon", "long", "longitude", "x", "coord x", "lon dms"],
    "Azimuth": ["azimuth", "azimut", "bearing", "az", "angulo", "ángulo", "direction", "sector azimuth", "azimuth_gis", "azimuth°"],
}

VALUE_MAP_TIPO = {
    "voice": "VOZ", "voz": "VOZ", "llamada": "VOZ", "call": "VOZ",
    "data": "DATOS", "datos": "DATOS", "gprs": "DATOS", "4g": "DATOS", "lte": "DATOS",
    "sms": "MENSAJES 2 VÍAS", "mensajes": "MENSAJES 2 VÍAS", "esms": "MENSAJES 2 VÍAS",
    "2vias": "MENSAJES 2 VÍAS", "2 vias": "MENSAJES 2 VÍAS", "smst": "MENSAJES 2 VÍAS",
    "esms;smst": "MENSAJES 2 VÍAS",
    "transfer": "TRANSFER", "desvio": "TRANSFER", "desvío": "TRANSFER", "forward": "TRANSFER"
}

DIR_MAP = {
    "ent": "ENTRANTE", "entrada": "ENTRANTE", "in": "ENTRANTE", "incoming": "ENTRANTE",
    "sal": "SALIENTE", "salida": "SALIENTE", "out": "SALIENTE", "outgoing": "SALIENTE"
}

# =============================================================================
# PARSERS NUMÉRICOS / DMS
# =============================================================================
NUM_RE = re.compile(r'[-+]?\d+(?:\.\d+)?')

def extract_number(text, prefer_last=True):
    if pd.isna(text):
        return np.nan
    nums = NUM_RE.findall(str(text))
    if not nums:
        return np.nan
    try:
        return float(nums[-1] if prefer_last else nums[0])
    except Exception:
        return np.nan

RE_DMS = re.compile(
    r"""^\s*
        (?P<deg>\d{1,3})[°\s]?
        (?P<min>\d{1,2})['\s]?
        (?P<sec>\d{1,2}(?:\.\d+)?)["\s]?
        (?P<hem>[NSEWnsew])?
        \s*$""",
    re.VERBOSE,
)

def dms_to_decimal(s: str) -> Optional[float]:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None
    if isinstance(s, (int, float)):
        return float(s)
    txt = str(s).strip()
    m = RE_DMS.match(txt)
    if not m:
        parts = re.split(r"[^\d\.A-Za-z]+", txt)
        parts = [p for p in parts if p]
        if 3 <= len(parts) <= 4:
            try:
                deg = float(parts[0]); minu = float(parts[1]); sec = float(parts[2])
                hem = parts[3].upper() if len(parts) == 4 else None
                val = deg + minu/60 + sec/3600
                if hem in ("S","W"):
                    val = -abs(val)
                return val
            except Exception:
                return None
        return None
    deg = float(m.group("deg")); minu = float(m.group("min")); sec = float(m.group("sec"))
    hem = (m.group("hem") or "").upper()
    val = deg + minu/60 + sec/3600
    if hem in ("S","W"):
        val = -abs(val)
    return val

def parse_maybe_dms(x):
    if pd.isna(x) or str(x).strip()=="":
        return np.nan
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        pass
    v = extract_number(x, prefer_last=True)
    if not (v is None or (isinstance(v, float) and math.isnan(v))):
        return v
    v = dms_to_decimal(str(x))
    return np.nan if v is None else v

# =============================================================================
# PARSERS ROBUSTOS DE FECHA/HORA
# =============================================================================
_time_full = re.compile(r'^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([APap]\.?M\.?)?\s*$')

def parse_excel_date_number(val) -> Optional[pd.Timestamp]:
    if pd.isna(val): return None
    if isinstance(val, (int,float)):
        if val > 59:
            ts = pd.to_datetime(val, unit='D', origin='1899-12-30', errors='coerce')
            if pd.notna(ts): return ts
    return None

def strip_time_from_date_string(s: str) -> str:
    if not isinstance(s, str): return s
    return re.sub(r'\s+\d{1,2}:\d{2}(?::\d{2})?(\s*[APap]\.?M\.?)?$', '', s.strip())

def parse_time_component(v) -> Optional[str]:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v,(int,float)):
        fv = float(v)
        if 0 <= fv < 1:
            total = int(round(fv*86400))
            h = total//3600; m=(total%3600)//60; s=total%60
            return f"{h:02d}:{m:02d}:{s:02d}"
        if 1 <= fv < 86400:
            h = int(fv)//3600; m=(int(fv)%3600)//60; s=int(fv)%60
            return f"{h:02d}:{m:02d}:{s:02d}"
    s = str(v).strip()
    m = _time_full.match(s)
    if m:
        h = int(m.group(1)); minute=int(m.group(2)); sec=int(m.group(3) or 0)
        ampm = (m.group(4) or "").lower()
        if ampm:
            if 'p' in ampm and h != 12: h += 12
            if 'a' in ampm and h == 12: h = 0
        if 0 <= h <= 23 and 0 <= minute <= 59 and 0 <= sec <= 59:
            return f"{h:02d}:{minute:02d}:{sec:02d}"
    ts = pd.to_datetime(s, errors='coerce')
    if pd.notna(ts):
        return ts.strftime("%H:%M:%S")
    return None

def parse_date_component(v) -> Optional[pd.Timestamp]:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    ts = parse_excel_date_number(v)
    if ts is not None:
        return ts.normalize()
    s = str(v).strip()
    if s == "":
        return None
    if _time_full.fullmatch(s):
        return None
    s2 = strip_time_from_date_string(s)
    # Priorizar formato mexicano dd/mm/yyyy
    for dayfirst in (True, False):
        ts = pd.to_datetime(s2, errors='coerce', dayfirst=dayfirst)
        if pd.notna(ts):
            return ts.normalize()
    return None

def robust_split_fecha_hora(src_date: Optional[pd.Series], src_time: Optional[pd.Series]) -> Tuple[pd.Series, pd.Series]:
    n = max(len(src_date) if src_date is not None else 0, len(src_time) if src_time is not None else 0)
    fechas, horas = [], []
    for i in range(n):
        vd = src_date.iloc[i] if src_date is not None and i < len(src_date) else None
        vt = src_time.iloc[i] if src_time is not None and i < len(src_time) else None
        dt_only = parse_date_component(vd)
        if dt_only is None and vt is not None:
            dt_only = parse_date_component(vt)
        hhmmss  = parse_time_component(vt)
        if hhmmss is None:
            m_hora = _time_full.search(str(vd) if vd is not None else "")
            if m_hora:
                hhmmss = parse_time_component(m_hora.group(0))
        if dt_only is None and hhmmss is None:
            # Fallback: volver a intentar usando dd/mm/yyyy como prioridad
            for dayfirst in (True, False):
                ts = pd.to_datetime(str(vd), errors='coerce', dayfirst=dayfirst)
                if pd.notna(ts):
                    dt_only = ts.normalize()
                    hhmmss = ts.strftime("%H:%M:%S")
                    break
        fechas.append(dt_only.strftime("%Y-%m-%d") if dt_only is not None else "")
        horas.append(hhmmss if hhmmss is not None else "")
    return pd.Series(fechas), pd.Series(horas)

# =============================================================================
# OTRAS NORMALIZACIONES
# =============================================================================
def guess_units_and_to_seconds(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    out = []
    for v in s:
        if v == "" or v.lower() in ("nan", "none"):
            out.append(np.nan); continue
        if re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", v):
            parts = [int(p) for p in v.split(":")]
            if len(parts)==3:
                sec = parts[0]*3600 + parts[1]*60 + parts[2]
            else:
                sec = parts[0]*60 + parts[1]
            out.append(sec); continue
        try:
            fv = float(v)
            out.append(int(round(fv/1000.0)) if fv > 60000 else int(round(fv)))
            continue
        except Exception:
            pass
        m = re.match(r"^(\d+(?:\.\d+)?)(ms|s)?$", v)
        if m:
            num = float(m.group(1)); unit = (m.group(2) or "s").lower()
            out.append(int(round(num/1000.0 if unit == "ms" else num)))
            continue
        out.append(np.nan)
    return pd.Series(out, index=series.index, dtype="Int64").astype("float").astype("Int64")

def normalize_tipo(s: pd.Series) -> pd.Series:
    x = s.astype(str).str.lower().str.strip()
    out = []
    for v in x:
        if v in VALUE_MAP_TIPO:
            out.append(VALUE_MAP_TIPO[v]); continue
        found = None
        for k, val in VALUE_MAP_TIPO.items():
            if k in v:
                found = val; break
        out.append(found if found else str(v).strip())
    return pd.Series(out, index=s.index).astype(str)

def normalize_direction(s: pd.Series) -> pd.Series:
    x = s.astype(str).str.lower().str.strip()
    out = []
    for v in x:
        found = ""
        for k, val in DIR_MAP.items():
            if v == k or k in v:
                found = val; break
        out.append(found)
    return pd.Series(out, index=s.index).astype(str)

# --- NUEVO: teléfonos sin decimales cuando NO se pide E.164 -------------------
def _plain_msisdn_no_plus(series: pd.Series) -> pd.Series:
    """Devuelve solo dígitos, sin .0 ni separadores; intenta conservar el valor exacto."""
    out = []
    for v in series:
        if pd.isna(v):
            out.append(""); continue
        # Numérico puro
        if isinstance(v, (int, np.integer)):
            out.append(str(int(v))); continue
        if isinstance(v, float):
            # Representación entera sin decimales (sirve para notación científica y X.0)
            out.append("{:.0f}".format(v)); continue
        txt = str(v).strip()
        # Caso típico '525611685889.0'
        if re.fullmatch(r"\d+\.0", txt):
            out.append(txt.split(".", 1)[0]); continue
        # Quitar separadores comunes sin perder dígitos
        txt = txt.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        # Si aún quedan letras/símbolos, extraer la PRIMERA racha larga de dígitos
        m = re.search(r"\d{7,}", txt)
        if m:
            out.append(m.group(0))
        else:
            # último recurso: eliminar todo lo que no sea dígito
            out.append(re.sub(r"\D+", "", txt))
    return pd.Series(out, index=series.index)

def normalize_msisdn_mx(series: pd.Series, enable_e164: bool) -> pd.Series:
    if not enable_e164:
        # Sin prefijo +52, pero SIN decimales ni '.0'
        return _plain_msisdn_no_plus(series)
    out = []
    for v in series.astype(str):
        digits = re.sub(r"\D+", "", v)
        if digits == "":
            out.append("")
            continue
        if digits.startswith("52") and len(digits) >= 12:
            out.append("+" + digits); continue
        if len(digits) == 10:
            out.append("+52" + digits); continue
        out.append("+" + digits)
    return pd.Series(out, index=series.index)

def to_int64_digits(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(r"\D+", "", regex=True),
                         errors="coerce").astype("Int64")

# =============================================================================
# AUTODETECCIÓN DE MAPEO
# =============================================================================
from difflib import get_close_matches

def suggest_mapping(src_cols: List[str], targets: List[str]) -> Dict[str, Optional[str]]:
    norm_src = {norm(c): c for c in src_cols}
    mapping = {t: None for t in targets}
    for tgt in targets:
        alias_list = SYNONYMS.get(tgt, [])
        chosen = None
        for alias in alias_list:
            a = norm(alias)
            if a in norm_src:
                chosen = norm_src[a]; break
        if not chosen and alias_list:
            candidates = get_close_matches(
                norm("|".join(alias_list)), list(norm_src.keys()), n=1, cutoff=0.85
            )
            if candidates:
                chosen = norm_src[candidates[0]]
        if not chosen and tgt == "Numero A":
            for key in ("a", "a party", "a_number", "from", "num_a"):
                k = norm(key)
                if k in norm_src: chosen = norm_src[k]; break
        if not chosen and tgt == "Numero B":
            for key in ("b", "b party", "b_number", "to", "dest"):
                k = norm(key)
                if k in norm_src: chosen = norm_src[k]; break
        mapping[tgt] = chosen
    return mapping

# =============================================================================
# UI – OPCIONES (FIJAS, SIN MOSTRAR BARRA LATERAL)
# =============================================================================
st.title(APP_TITLE)
st.caption("Mapea cualquier CDR (AT&T u otros) al esquema TELCEL_CRUDO de 11 columnas. Incluye normalización de teléfonos, fechas/horas, duración, coordenadas y composición SERV+T_REG.")

# Valores fijos equivalentes a los que tenías en la barra lateral
opt_norm_msisdn = False                      # Normalizar teléfonos a E.164 MX (+52…)
opt_fix_west = True                          # Forzar LONGITUD negativa (hemisferio Oeste)
opt_drop_empty_coords = False                # Descartar filas sin coordenadas válidas
opt_prefer_last_in_brackets = True           # Si LAT/LON/Azimuth vienen como [a:b], tomar el último

opt_add_dir_to_tipo = True                   # Agregar ENT/SAL a VOZ y MENSAJES 2 VÍAS
opt_add_dir_to_datos = False                 # Agregar ENT/SAL también a DATOS

opt_sort_dt = True                           # Ordenar por Fecha+Hora ascendente
opt_export_ab_int = True                     # Exportar Numero A/B como enteros (sin decimales)
out_name = "CRUDO_UNIFICADO"                 # Nombre base del archivo de salida

# =============================================================================
# CARGA
# =============================================================================
file = st.file_uploader("Sube un CDR .xlsx/.xls/.csv/.txt", type=["xlsx","xls","csv","txt"])

st.info(
    "- Si Fecha y Hora vienen en una sola columna, selecciónala en cualquiera; el parser la dividirá.\n"
    "- Duración acepta hh:mm:ss, mm:ss, ms o segundos.\n"
    "- LAT/LON en DMS o con corchetes tipo `[23.24:23.25]` se convierten automáticamente."
)

def read_any(uploaded):
    name = uploaded.name.lower()
    ext = name.split(".")[-1]
    raw = uploaded.getvalue()
    if ext in ("xlsx", "xls"):
        xls = pd.ExcelFile(io.BytesIO(raw))
        sh = st.selectbox("Hoja de Excel", xls.sheet_names, index=0)
        df = pd.read_excel(io.BytesIO(raw), sheet_name=sh)
        return df
    else:
        text = raw.decode("utf-8", errors="ignore")
        sep_counts = {",": text.count(","), "\t": text.count("\t"), ";": text.count(";")}
        sep = max(sep_counts, key=sep_counts.get)
        df = pd.read_csv(io.StringIO(text), sep=sep)
        return df

if file:
    try:
        df = read_any(file)
    except Exception as e:
        st.error(f"Error leyendo archivo: {e}")
        st.stop()

    st.subheader("1) Columnas detectadas")
    st.write(list(df.columns))

    # =============================================================================
    # EDITOR DE MAPEO
    # =============================================================================
    st.subheader("2) Mapeo de columnas (editable)")

    MAPPING_FIELDS = [
        "Telefono", "Tipo", "Dirección (ENT/SAL)", "Numero A", "Numero B", "Fecha",
        "Hora", "Durac. Seg.", "IMEI", "LATITUD", "LONGITUD", "Azimuth"
    ]

    suggested = suggest_mapping(list(df.columns), MAPPING_FIELDS)
    cols_ui = st.columns(3)
    mapping_user: Dict[str, Optional[str]] = {}
    choices = ["<vacío>"] + list(df.columns)

    for idx, tgt in enumerate(MAPPING_FIELDS):
        default = suggested.get(tgt)
        default_idx = choices.index(default) if default in choices else 0
        mapping_user[tgt] = cols_ui[idx % 3].selectbox(
            f"{tgt} ←", choices, index=default_idx
        )
        if mapping_user[tgt] == "<vacío>":
            mapping_user[tgt] = None

    recipe = {"target": "TELCEL_CRUDO", "mapping": mapping_user}
    recipe_bytes = json.dumps(recipe, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button("💾 Descargar receta JSON", recipe_bytes, file_name="receta_compilador.json")

    # =============================================================================
    # CONVERSIÓN / NORMALIZACIÓN
    # =============================================================================
    st.subheader("3) Conversión / Normalización")

    if st.button("Convertir y Normalizar", type="primary"):
        log_rows = []

        def col_or_empty(sel: Optional[str]) -> pd.Series:
            if sel is None or sel not in df.columns:
                return pd.Series([""] * len(df))
            return df[sel]

        s_tel = col_or_empty(mapping_user["Telefono"])
        s_tipo_serv = col_or_empty(mapping_user["Tipo"])
        s_dir = col_or_empty(mapping_user["Dirección (ENT/SAL)"])
        s_a   = col_or_empty(mapping_user["Numero A"])
        s_b   = col_or_empty(mapping_user["Numero B"])
        s_f   = col_or_empty(mapping_user["Fecha"])
        s_h   = col_or_empty(mapping_user["Hora"])
        s_dur = col_or_empty(mapping_user["Durac. Seg."])
        s_imei= col_or_empty(mapping_user["IMEI"])
        s_lat = col_or_empty(mapping_user["LATITUD"])
        s_lon = col_or_empty(mapping_user["LONGITUD"])
        s_azi = col_or_empty(mapping_user["Azimuth"])

        # Fecha y Hora
        fecha_out, hora_out = robust_split_fecha_hora(s_f, s_h)

        # Duración
        dur_out = guess_units_and_to_seconds(s_dur)

        # Tipo + Dirección
        tipo_serv = normalize_tipo(s_tipo_serv)
        dire_norm = normalize_direction(s_dir)
        if opt_add_dir_to_tipo or opt_add_dir_to_datos:
            tipo_out = pd.Series([
                (f"{t} {d}" if not (t == "DATOS" and not opt_add_dir_to_datos) and d else t)
                for t, d in zip(tipo_serv.astype(str), dire_norm.astype(str))
            ], index=tipo_serv.index)
        else:
            tipo_out = tipo_serv

        # Teléfonos
        tel_out = normalize_msisdn_mx(s_tel, opt_norm_msisdn)
        a_out   = normalize_msisdn_mx(s_a, opt_norm_msisdn)
        b_out   = normalize_msisdn_mx(s_b, opt_norm_msisdn)

        # Coordenadas
        def coord_any(x):
            v = extract_number(x, prefer_last=opt_prefer_last_in_brackets)
            if pd.isna(v):
                v = parse_maybe_dms(x)
            return v

        lat_out = s_lat.apply(coord_any)
        lon_out = s_lon.apply(coord_any)
        lat_out = lat_out.where(lat_out != 0, np.nan)
        lon_out = lon_out.where(lon_out != 0, np.nan)
        if opt_fix_west:
            lon_out = -lon_out.abs()

        # Azimuth
        azi_out = s_azi.apply(lambda x: extract_number(x, prefer_last=opt_prefer_last_in_brackets)).astype(float)

        out = pd.DataFrame({
            "Telefono": tel_out.astype(str).str.strip(),
            "Tipo": tipo_out.astype(str),
            "Numero A": a_out.astype(str),
            "Numero B": b_out.astype(str),
            "Fecha": fecha_out,
            "Hora": hora_out,
            "Durac. Seg.": dur_out.astype("Int64"),
            "IMEI": s_imei.astype(str).str.replace(r"\.0$", "", regex=True).str.strip().replace({"nan": ""}),
            "LATITUD": lat_out,
            "LONGITUD": lon_out,
            "Azimuth": azi_out
        }).reset_index(drop=True)

        # Validaciones
        lat_bad = (~out["LATITUD"].between(-90, 90)) & (~out["LATITUD"].isna())
        lon_bad = (~out["LONGITUD"].between(-180, 180)) & (~out["LONGITUD"].isna())
        if lat_bad.any() or lon_bad.any():
            log_rows.append({"tipo":"WARN","detalle":f"Coordenadas fuera de rango. LAT malas: {int(lat_bad.sum())}, LON malas: {int(lon_bad.sum())}"})

        # Ordenar por Fecha+Hora (sin inventar fechas)
        dt = pd.to_datetime(
            out["Fecha"].astype(str).str.strip() + " " + out["Hora"].astype(str).str.strip(),
            errors="coerce"
        )
        out["_dt"] = dt
        out["_idx"] = np.arange(len(out))
        if opt_sort_dt:
            out = out.sort_values(by=["_dt", "_idx"], ascending=[True, True], na_position="last").reset_index(drop=True)

        # Opcional: filtrar coords vacías
        if opt_drop_empty_coords:
            out = out[~(out["LATITUD"].isna() | out["LONGITUD"].isna())].reset_index(drop=True)

        # A/B como enteros si se solicita (para Excel sin decimales)
        if opt_export_ab_int:
            out["Numero A"] = to_int64_digits(out["Numero A"])
            out["Numero B"] = to_int64_digits(out["Numero B"])

        # LOG
        log_rows.append({"tipo":"INFO","detalle":f"Filas entrada: {len(df)}, filas salida: {len(out)}"})
        log_rows.append({"tipo":"INFO","detalle":f"Mapeo aplicado: {json.dumps(mapping_user, ensure_ascii=False)}"})
        fake_1900 = int((out["Fecha"] == "1900-01-01").sum())
        fake_1970 = int((out["Fecha"] == "1970-01-01").sum())
        log_rows.append({"tipo":"CHK","detalle":f"Fechas=1900-01-01: {fake_1900}, Fechas=1970-01-01: {fake_1970}"})
        for c in TARGET_COLUMNS:
            if c in out.columns:
                n_nulls = int(out[c].isna().sum() + (out[c] == "").sum())
                log_rows.append({"tipo":"NULLS","detalle":f"{c}: {n_nulls} nulos/vacíos"})
        log_df = pd.DataFrame(log_rows)

        # Vista previa
        st.success("Conversión realizada.")
        st.markdown("**Vista previa (primeras 100 filas):**")
        st.dataframe(out.drop(columns=["_dt","_idx"]).head(100), use_container_width=True)

        # =============================================================================
        # EXPORTACIÓN (fallback xlsxwriter → openpyxl)
        # =============================================================================
        bio = io.BytesIO()
        try:
            import xlsxwriter  # noqa: F401
            engine_name = "xlsxwriter"
        except Exception:
            engine_name = "openpyxl"

        with pd.ExcelWriter(bio, engine=engine_name) as writer:
            out_final = out.drop(columns=["_dt","_idx"])
            out_final.to_excel(writer, sheet_name="CRUDO_UNIFICADO", index=False)
            log_df.to_excel(writer, sheet_name="LOG_Mapeo", index=False)

            if engine_name == "xlsxwriter":
                workbook = writer.book
                ws = writer.sheets["CRUDO_UNIFICADO"]
                fmt_int = workbook.add_format({"num_format": "0"})
                try:
                    cols_final = out_final.columns
                    if "Numero A" in cols_final and "Numero B" in cols_final:
                        col_a = cols_final.get_loc("Numero A")
                        col_b = cols_final.get_loc("Numero B")
                        ws.set_column(col_a, col_a, 18, fmt_int)
                        ws.set_column(col_b, col_b, 18, fmt_int)
                except Exception:
                    pass
            # En openpyxl no aplicamos formato de columna

        st.download_button(
            label="⬇️ Descargar Excel (CRUDO_UNIFICADO + LOG)",
            data=bio.getvalue(),
            file_name=f"{out_name}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        st.download_button(
            label="⬇️ Descargar CSV (solo datos)",
            data=out.drop(columns=["_dt","_idx"]).to_csv(index=False).encode("utf-8"),
            file_name=f"{out_name}.csv",
            mime="text/csv"
        )

else:
    st.info("Sube un CDR para comenzar. Soporta .xlsx/.xls/.csv/.txt.")
