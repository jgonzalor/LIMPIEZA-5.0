# pages/app_linea_tiempo.py
# Go Mapper · Línea de Tiempo (pestaña independiente, PDF landscape)
# - XLSX limpio -> línea de tiempo por día (VOZ/SMS/DATOS sin texto en barras)
# - Tabla: Contacto (VOZ/SMS = contraparte; DATOS = APN), Detalle (ubicación antena), Plus/Coord con link a Maps
# - Descargas: HTML del día (nombre largo), ZIP de días, PDF del día (nombre largo, ORIENTACIÓN HORIZONTAL)
# - Render estable: st.markdown (sin st.components)
# - PDF robusto: fpdf2; registra fuente Unicode si existe; si no, sanitiza para Helvetica

import os, re, io, zipfile, urllib.parse
from core.datetime_utils import parse_local_datetime
import streamlit.components.v1 as components
from ui.components import render_page_header
from datetime import datetime, timedelta
import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")
import pandas as pd
from fpdf import FPDF

# 🔐 Guardián central de la suite y navegación
from guardian import login_guard
from suite_nav import render_suite_sidebar

# tus otros imports...

# --- CONFIGURACIÓN DE PÁGINA ---
pass  # Page configuration is initialized before rendering.

# --- GUARDIÁN DE ACCESO A LA SUITE ---
if not login_guard():
    st.stop()
# --- FIN GUARDIÁN ---

# --- MENÚ LATERAL DE LA SUITE ---
render_suite_sidebar()
# --- FIN MENÚ LATERAL ---

render_page_header("Línea de tiempo", "Explora la secuencia diaria de comunicaciones y exporta HTML o PDF.", tags=["Cronología", "America/Mazatlan"])

st.markdown("""
Sube el **XLSX limpio** generado por la app de **Limpieza**. Detecto columnas comunes de forma automática.
Si tu archivo trae **PLUS_CODE** y/o **Lat/Lon**, crearé enlaces a **Google Maps** en la tabla.
""")

# ===================== utilidades =====================

def normaliza_txt(s: str) -> str:
    if s is None: return ""
    s = str(s)
    trans = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")
    return s.translate(trans).strip().lower()

def pick_mejor_hoja(xls: pd.ExcelFile) -> str:
    mejor, punt = None, -1
    claves = ["fecha","hora","tipo","numero origen","numero destino","duracion",
              "latitud","longitud","plus_code","pluscode","plus code",
              "plus_code_nombre","etiqueta de localizacion","t_reg","serv",
              "apn","direccion de internet","linea","msisdn"]
    for sh in xls.sheet_names:
        try:
            df = xls.parse(sh, nrows=50)
        except Exception:
            continue
        cols = [normaliza_txt(c) for c in df.columns]
        score = sum(sum(1 for c in cols if k in c) for k in claves)
        if score > punt:
            punt, mejor = score, sh
    return mejor or xls.sheet_names[0]

def find_col(df: pd.DataFrame, candidatos):
    for c in candidatos:
        for col in df.columns:
            if c in normaliza_txt(col):
                return col
    return None

def parse_dt(fecha, hora):
    if (pd.isna(fecha) if hasattr(pd, "isna") else fecha is None) and (pd.isna(hora) if hasattr(pd, "isna") else hora is None):
        return None
    sdate = "" if pd.isna(fecha) else str(fecha)
    shour = "" if pd.isna(hora) else str(hora)
    try:
        if shour and " " in shour and ":" in shour and not sdate:
            ts = pd.to_datetime(shour, dayfirst=True, errors="coerce")
        else:
            ts = pd.to_datetime((sdate+" "+shour).strip(), dayfirst=True, errors="coerce")
        if pd.isna(ts):
            ts = pd.to_datetime(sdate, dayfirst=True, errors="coerce")
    except Exception:
        ts = pd.NaT
    return None if pd.isna(ts) else ts.to_pydatetime()

def parse_duracion(v):
    if pd.isna(v): return None
    s = str(v).strip()
    if not s: return None
    if ":" in s:
        parts = [p or "0" for p in s.split(":")]
        try:
            parts = [int(float(p)) for p in parts]
        except Exception:
            parts = [0,0,0]
        while len(parts) < 3: parts.insert(0,0)
        h,m,sec = parts[-3], parts[-2], parts[-1]
        return timedelta(hours=h, minutes=m, seconds=sec)
    try:
        return timedelta(seconds=int(float(s)))
    except Exception:
        return None

APN_RE = re.compile(r'\b(?:internet|wap|mms|web)\.[\w\.-]+', re.IGNORECASE)
def extrae_apn(row, col_apn, col_tipo):
    if col_apn:
        val = row.get(col_apn)
        if pd.notna(val) and str(val).strip():
            m = APN_RE.search(str(val))
            return m.group(0) if m else str(val).strip()
    if col_tipo:
        val = row.get(col_tipo)
        if pd.notna(val):
            m = APN_RE.search(str(val))
            if m: return m.group(0)
    for v in row.values:
        if isinstance(v, str) and "internet" in v.lower():
            m = APN_RE.search(v)
            if m: return m.group(0)
    return "APN no informado"

def infiere_sentido(tipo_full: str, treg_val: str) -> str:
    txt = normaliza_txt(f"{tipo_full} {treg_val}")
    if ("entrante" in txt) or ("recib" in txt) or txt.startswith("ent") or " ent" in txt:
        return "ENT"
    if ("saliente" in txt) or ("orig" in txt) or txt.startswith("sal") or " sal" in txt:
        return "SAL"
    return "—"

def link_maps(plus_code, lat, lon, etiqueta):
    if plus_code and str(plus_code).strip():
        q = urllib.parse.quote_plus(str(plus_code).strip())
        return f"https://www.google.com/maps/search/?api=1&query={q}"
    if pd.notna(lat) and pd.notna(lon):
        try:
            q = urllib.parse.quote_plus(f"{float(lat):.6f},{float(lon):.6f}")
            return f"https://www.google.com/maps/search/?api=1&query={q}"
        except Exception:
            pass
    if etiqueta and str(etiqueta).strip():
        q = urllib.parse.quote_plus(str(etiqueta).strip())
        return f"https://www.google.com/maps/search/?api=1&query={q}"
    return ""

def texto_plus(plus_code, lat, lon):
    if plus_code and str(plus_code).strip(): return str(plus_code).strip()
    if pd.notna(lat) and pd.notna(lon):
        try:
            return f"{float(lat):.5f},{float(lon):.5f}"
        except Exception:
            return f"{lat},{lon}"
    return "—"

def esc_html(s: str) -> str:
    from html import escape
    return escape(str(s), quote=True)

# ===================== construcción de eventos =====================

def construir_eventos(df: pd.DataFrame) -> pd.DataFrame:
    col_a        = find_col(df, ["numero origen","numero a","telefono a","telefono","msisdn","linea"])
    col_b        = find_col(df, ["numero destino","numero b","telefono b","destino"])
    col_datetime = find_col(df, ["datetime", "fechahora", "fecha y hora"])
    col_fecha    = find_col(df, ["fecha de la comunicacion","fecha","fecha_evento"])
    col_hora     = find_col(df, ["hora de la comunicacion","hora"])
    col_tipo     = find_col(df, ["tipo de comunicacion","tipo","serv"])
    col_treg     = find_col(df, ["t_reg","direccion","sentido","dir"])
    col_duracion = find_col(df, ["duracion","duración","tiempo","segundos"])
    col_lat      = find_col(df, ["latitud","lat"])
    col_lon      = find_col(df, ["longitud","lon","lng"])
    col_plusname = find_col(df, ["plus_code_nombre","etiqueta de localizacion","etiqueta","ubicacion"])
    col_plusraw  = next((c for c in df.columns if normaliza_txt(c) in {"plus_code","plus code","pluscode"}), None)
    col_apn      = find_col(df, ["apn","direccion de internet","dir internet","apn datos","apn de datos"])

    linea = None
    if col_a is not None:
        ser = df[col_a].dropna().astype(str)
        if len(ser) > 0:
            linea = ser.value_counts().idxmax()

    eventos = []
    for _, row in df.iterrows():
        ini = parse_local_datetime(row.get(col_datetime))
        if pd.isna(ini):
            ini = parse_local_datetime(row.get(col_fecha), row.get(col_hora))
        if pd.isna(ini):
            continue
        dur = parse_duracion(row.get(col_duracion))
        fin = ini + dur if dur else None

        tipo_full = str(row.get(col_tipo)).strip() if col_tipo else ""
        tnorm = normaliza_txt(tipo_full)
        if ("voz" in tnorm) or ("llamada" in tnorm):
            tipo_main = "VOZ"
        elif ("sms" in tnorm) or ("mensaje" in tnorm):
            tipo_main = "SMS"
        elif ("datos" in tnorm) or ("gprs" in tnorm) or ("internet" in tnorm):
            tipo_main = "DATOS"
        else:
            tipo_main = "OTRO"

        sentido = infiere_sentido(tipo_full, str(row.get(col_treg)) if col_treg else "")
        a_num = str(row.get(col_a)).strip() if col_a and not pd.isna(row.get(col_a)) else ""
        b_num = str(row.get(col_b)).strip() if col_b and not pd.isna(row.get(col_b)) else ""

        if tipo_main in ("VOZ","SMS"):
            if sentido == "SAL": contacto = b_num or ""
            elif sentido == "ENT": contacto = a_num or ""
            else: contacto = b_num or a_num or ""
            contacto = contacto if contacto else "—"
        elif tipo_main == "DATOS":
            contacto = extrae_apn(row, col_apn, col_tipo)
        else:
            contacto = "—"

        etiq = row.get(col_plusname) if col_plusname else None
        lat  = row.get(col_lat) if col_lat else None
        lon  = row.get(col_lon) if col_lon else None
        plus = row.get(col_plusraw) if col_plusraw else None

        if pd.notna(etiq) and str(etiq).strip():
            detalle = str(etiq).strip()
        elif pd.notna(lat) and pd.notna(lon):
            try:
                detalle = f"{float(lat):.5f}, {float(lon):.5f}"
            except Exception:
                detalle = f"{lat}, {lon}"
        else:
            detalle = "—"

        tip = f"{tipo_full} | {detalle} | Contacto: {contacto}"

        eventos.append({
            "Linea": f"Línea {linea}" if linea else "Línea",
            "Inicio": ini,
            "Fin": fin,
            "Fecha": ini.date(),
            "TipoCompleto": tipo_full if tipo_full else tipo_main,
            "TipoMain": tipo_main,
            "Contacto": contacto,
            "DetalleUbicacion": detalle,
            "PlusTxt": texto_plus(plus, lat, lon),
            "PlusLink": link_maps(plus, lat, lon, etiq),
            "Tooltip": tip
        })
    if not eventos:
        return pd.DataFrame(columns=["Inicio", "Fin", "Fecha", "TipoMain"])
    evdf = pd.DataFrame(eventos).sort_values("Inicio").reset_index(drop=True)
    return evdf

# ===================== render HTML por día =====================

def render_html_dia(day_df: pd.DataFrame, day_date) -> str:
    if day_df.empty:
        return "<p>No hay eventos para este día.</p>"
    day_df = day_df.copy()
    # Preserve unknown event categories.

    linea = day_df["Linea"].iloc[0]
    day_start = datetime.combine(day_date, datetime.min.time())
    day_end   = day_start + timedelta(days=1)
    total_min = (day_end - day_start).total_seconds()/60.0

    def pos_pct(ts): return (ts - day_start).total_seconds()/60.0/total_min*100.0

    ticks = []
    t = day_start
    while t <= day_end:
        ticks.append((t, t.strftime("%H:%M")))
        t += timedelta(hours=1)

    html = f"""<!DOCTYPE html>
<html lang="es">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Línea de tiempo – {day_date}</title>
<style>
:root {{ --bg:#fff; --ink:#0b0b0b; --muted:#374151; --grid:#cbd5e1;
        --voz:#2563eb; --sms:#10b981; --datos:#7c3aed; }}
body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin:16px; color:var(--ink); }}
h1 {{ margin:0 0 4px; font-size:20px; }}
.muted {{ color:var(--muted); }}
.legend {{ display:flex; gap:14px; align-items:center; margin:8px 0 10px 0; font-size:13px; color:var(--muted); }}
.key {{ display:inline-flex; align-items:center; gap:6px; }}
.box {{ width:14px; height:14px; border-radius:3px; display:inline-block; }}
.timeline {{ border:2px solid var(--grid); border-radius:12px; padding:12px; }}
.header {{ display:grid; grid-template-columns: 220px 1fr; gap:10px; align-items:end; padding:8px; }}
.scale {{ position:relative; height:40px; border-left:2px solid var(--grid);}}
.tick {{ position:absolute; top:0; transform:translateX(-1px); width:2px; height:100%; background:var(--grid);}}
.label {{ position:absolute; top:42px; font-size:12px; color:var(--muted); transform:translateX(-50%);}}
.row {{ display:grid; grid-template-columns: 220px 1fr; gap:10px; padding:12px 8px; border-top:2px dashed var(--grid);}}
.name {{ font-weight:700; font-size:15px; }}
.track {{ position:relative; height:60px; background:repeating-linear-gradient(90deg,transparent,transparent 59px, rgba(203,213,225,.5) 60px); border-radius:8px; overflow:hidden; }}
.bar, .dot {{ position:absolute; top:14px; }}
.bar {{ height:32px; border-radius:6px; }}
.bar.voz {{ background:var(--voz);}}
.bar.datos {{ background:var(--datos);}}
.dot.sms {{ width:12px; height:12px; border-radius:50%; background:var(--sms);}}
.table {{ margin-top:16px; border:2px solid var(--grid); border-radius:10px; overflow:hidden; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th, td {{ padding:8px 10px; border-bottom:1px solid var(--grid); text-align:left; }}
th {{ background:#f1f5f9; font-weight:700; }}
.small {{ color:var(--muted); font-size:12px; }}
a.map {{ color:#2563eb; text-decoration:none; }}
a.map:hover {{ text-decoration:underline; }}
</style>
<body>
<h1>Línea de tiempo – {day_date}</h1>
<p class="muted">Línea: <b>{esc_html(linea)}</b> · Eventos: <b>{len(day_df)}</b></p>
<div class="legend">
  <span class="key"><span class="box" style="background:var(--voz)"></span> VOZ</span>
  <span class="key"><span class="box" style="background:var(--sms); border-radius:50%"></span> SMS</span>
  <span class="key"><span class="box" style="background:var(--datos)"></span> DATOS</span>
</div>
<div class="timeline">
  <div class="header">
    <div></div>
    <div class="scale">
"""
    for ts,label in ticks:
        left = pos_pct(ts)
        html += f'      <div class="tick" style="left:{left:.4f}%"></div>\n'
        html += f'      <div class="label" style="left:{left:.4f}%">{label}</div>\n'
    html += "    </div>\n  </div>\n"
    html += f'  <div class="row">\n    <div class="name">{esc_html(linea)}</div>\n    <div class="track">\n'

    for _, r in day_df.iterrows():
        left = pos_pct(r["Inicio"])
        width = ((r["Fin"]-r["Inicio"]).total_seconds()/60.0/total_min*100.0) if pd.notna(r["Fin"]) else 0.0
        tip = esc_html(r["Tooltip"])
        if r["TipoMain"]=="VOZ":
            html += f'      <div class="bar voz" title="{tip}" style="left:{left:.4f}%; width:{max(width,0.3):.4f}%"></div>\n'
        elif r["TipoMain"]=="DATOS":
            html += f'      <div class="bar datos" title="{tip}" style="left:{left:.4f}%; width:{max(width,0.3):.4f}%"></div>\n'
        elif r["TipoMain"]=="SMS":
            html += f'      <div class="dot sms" title="{tip}" style="left:{left:.4f}%"></div>\n'
        else:
            html += f'      <div class="bar datos" title="{tip}" style="left:{left:.4f}%; width:{max(width,0.3):.4f}%"></div>\n'

    html += "    </div>\n  </div>\n</div>\n"

    # Tabla
    html += """
<div class="table">
<table>
<thead>
<tr>
  <th>Inicio</th><th>Fin</th><th>Tipo</th><th>Contacto</th><th>Detalle (Ubicación antena)</th><th>Plus code / Coordenada</th>
</tr>
</thead>
<tbody>
"""
    for _, r in day_df.iterrows():
        i = r["Inicio"].strftime("%H:%M:%S")
        f = r["Fin"].strftime("%H:%M:%S") if pd.notna(r["Fin"]) else "—"
        plus_txt = esc_html(r["PlusTxt"]); link = r["PlusLink"]
        plus_html = f'<a class="map" href="{esc_html(link)}" target="_blank" rel="noopener">{plus_txt}</a>' if link else plus_txt
        html += f"<tr><td>{i}</td><td>{f}</td><td>{esc_html(r['TipoCompleto'])}</td><td>{esc_html(r['Contacto'])}</td><td>{esc_html(r['DetalleUbicacion'])}</td><td>{plus_html}</td></tr>\n"

    html += """
</tbody>
</table>
</div>
<p class="small">Barras sin texto interno; leyenda VOZ/SMS/DATOS; tooltips al pasar el mouse. Plus code/Coordenada abre Google Maps.</p>
</body></html>
"""
    return html

# ===================== PDF (fpdf2) — HORIZONTAL =====================

UNICODE_REGULAR_CANDS = [
    "assets/fonts/DejaVuSansCondensed.ttf",
    "assets/fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
UNICODE_BOLD_CANDS = [
    "assets/fonts/DejaVuSansCondensed-Bold.ttf",
    "assets/fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

def _sanitize_for_corefont(text: str) -> str:
    if text is None: return ""
    s = str(text)
    repl = {"…":"...", "—":"-", "–":"-", "“":'"', "”":'"', "‘":"'","’":"'","\u00A0":" "}
    for k,v in repl.items(): s = s.replace(k,v)
    return s

def _trunc(s, n):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:max(0, n-3)] + "..."

def _init_pdf_landscape():
    """
    Crea FPDF en orientación horizontal y registra fuente Unicode regular y opcional Bold.
    Retorna: (pdf, use_unicode(bool), uni_family(str|""), uni_bold_family(str|""))
    """
    pdf = FPDF(orientation="L", unit="mm", format="A4")  # ← Landscape
    pdf.set_auto_page_break(auto=True, margin=15)
    use_unicode, uni_family, uni_bold = False, "", ""
    reg = next((p for p in UNICODE_REGULAR_CANDS if os.path.exists(p)), None)
    if reg:
        try:
            pdf.add_font("DejaVu", "", reg, uni=True)
            use_unicode, uni_family = True, "DejaVu"
            bold = next((p for p in UNICODE_BOLD_CANDS if os.path.exists(p)), None)
            if bold:
                pdf.add_font("DejaVuBold", "", bold, uni=True)
                uni_bold = "DejaVuBold"
        except Exception:
            use_unicode, uni_family, uni_bold = False, "", ""
    return pdf, use_unicode, uni_family, uni_bold

def timeline_pdf_bytes(day_df: pd.DataFrame, day_date) -> bytes:
    pdf, use_uni, uni_family, uni_bold = _init_pdf_landscape()
    pdf.add_page()

    def set_font(size=12, bold=False):
        if use_uni:
            fam = (uni_bold if (bold and uni_bold) else uni_family) or "DejaVu"
            pdf.set_font(fam, "", size)  # TTF usa style vacío
        else:
            pdf.set_font("Helvetica", "B" if bold else "", size)

    def safe(text: str) -> str:
        return text if use_uni else _sanitize_for_corefont(text)

    # Título
    titulo = f'Linea de Tiempo "{day_date}" Suite Go Mapper.'
    set_font(14, bold=True)
    pdf.cell(0, 8, safe(titulo), ln=1)

    # Subtítulo
    linea = str(day_df["Linea"].iloc[0]) if not day_df.empty else "Línea"
    set_font(10, bold=False)
    pdf.set_text_color(100,100,100)
    pdf.cell(0, 6, safe(f"{linea} · Eventos: {len(day_df)}"), ln=1)
    pdf.set_text_color(0,0,0)

    # Geometría dinámica (landscape)
    page_w = pdf.w  # ~297mm
    left, right = 15, page_w - 15
    avail = right - left

    # Leyenda
    def box(label, r,g,b):
        x, y = pdf.get_x(), pdf.get_y()
        pdf.set_fill_color(r,g,b); pdf.rect(x, y, 5, 5, style="F")
        pdf.set_xy(x+6, y-0.5); set_font(9)
        pdf.cell(18, 6, safe(label))
        pdf.set_xy(x+24, y)

    pdf.ln(2)
    box("VOZ",  37, 99,235)
    box("SMS",  16,185,129)
    box("DATOS",124, 58,237)
    pdf.ln(8)

    # Timeline (más ancho en landscape)
    top, height = pdf.get_y()+2, 22
    pdf.set_draw_color(203,213,225)
    for h in range(25):
        x = left + avail*(h/24.0)
        pdf.line(x, top, x, top+height)
        set_font(7)
        pdf.set_text_color(100,100,100)
        pdf.text(x-4, top+height+4, f"{h:02d}:00")
    pdf.set_text_color(0,0,0)

    if not day_df.empty:
        day_df = day_df.copy()
        # Preserve unknown event categories.

    day_date_start = datetime.combine(day_date, datetime.min.time())
    def x_of(ts):
        mins = max(0, min(1440, (ts - day_date_start).total_seconds()/60.0))
        return left + avail*(mins/1440.0)

    for _, r in day_df.iterrows():
        ini = r["Inicio"].to_pydatetime() if hasattr(r["Inicio"], "to_pydatetime") else r["Inicio"]
        fin = r.get("Fin")
        if fin is None or not pd.notna(fin):
            fin = ini + timedelta(seconds=60)
        else:
            fin = fin.to_pydatetime() if hasattr(fin, "to_pydatetime") else fin
        tipo = r.get("TipoMain","DATOS")
        if   tipo in ("VOZ","VOX"):
            pdf.set_fill_color(37,99,235)
            pdf.rect(x_of(ini), top+4, max(1, x_of(fin)-x_of(ini)), 9, style="F")
        elif tipo=="SMS":
            pdf.set_fill_color(16,185,129)
            x = x_of(ini); y = top+8
            pdf.ellipse(x-1.6, y-1.6, 3.2, 3.2, style="F")
        else:
            pdf.set_fill_color(124,58,237)
            pdf.rect(x_of(ini), top+4, max(1, x_of(fin)-x_of(ini)), 9, style="F")

    pdf.ln(height+12)

    # Tabla — anchos en porcentaje del ancho útil (avail)
    # 9% 9% 12% 20% 35% 15%  => total 100%
    w_i = avail*0.09; w_f = avail*0.09; w_tipo = avail*0.12
    w_cont = avail*0.20; w_det = avail*0.35; w_plus = avail*0.15

    set_font(9, bold=True)
    pdf.cell(w_i,   6, safe("Inicio"))
    pdf.cell(w_f,   6, safe("Fin"))
    pdf.cell(w_tipo,6, safe("Tipo"))
    pdf.cell(w_cont,6, safe("Contacto"))
    pdf.cell(w_det, 6, safe("Detalle (Ubicación)"))
    pdf.cell(w_plus,6, safe("Plus/Coord"), ln=1)
    set_font(8, bold=False)

    for _, r in day_df.iterrows():
        try: i = r["Inicio"].strftime("%H:%M:%S")
        except Exception: i = "-"
        try: f = r["Fin"].strftime("%H:%M:%S") if pd.notna(r["Fin"]) else "—"
        except Exception: f = "—"
        pdf.cell(w_i,   5, safe(i))
        pdf.cell(w_f,   5, safe(f))
        pdf.cell(w_tipo,5, safe(_trunc(r.get("TipoCompleto",""), 22)))
        pdf.cell(w_cont,5, safe(_trunc(r.get("Contacto","-"), 34)))
        pdf.cell(w_det, 5, safe(_trunc(r.get("DetalleUbicacion","-"), 58)))
        pdf.cell(w_plus,5, safe(_trunc(r.get("PlusTxt","-"), 20)), ln=1)

    result = pdf.output(dest="S")
    return bytes(result) if isinstance(result, (bytes, bytearray)) else result.encode("latin1")

# ===================== UI principal =====================

archivo = st.file_uploader("Sube el XLSX limpio (salida de Limpieza)", type=["xlsx"])
if archivo is None:
    st.info("Carga un XLSX para comenzar.")
    st.stop()

try:
    xls = pd.ExcelFile(archivo)
    hoja = pick_mejor_hoja(xls)
    base = xls.parse(hoja)
except Exception as e:
    st.error(f"No pude abrir el XLSX. Detalle: {e}")
    st.stop()

evdf = construir_eventos(base)
if evdf.empty:
    st.warning("No se pudieron derivar eventos con fecha/hora del archivo.")
    st.stop()

# Filtros
col1, col2, col3 = st.columns([1,1,2])
with col1:
    fechas_disp = sorted(evdf["Fecha"].unique())
    def _fmt(d):
        try:    return d.strftime("%Y-%m-%d")
        except: return str(d)
    fecha_sel = st.selectbox("Día", options=fechas_disp, index=0, format_func=_fmt)
with col2:
    tipos_on = st.multiselect("Tipos a mostrar", options=["VOZ","SMS","DATOS","OTRO"], default=["VOZ","SMS","DATOS","OTRO"])

df_dia = evdf[(evdf["Fecha"]==fecha_sel) & (evdf["TipoMain"].isin(tipos_on))].copy()

# Render HTML embebido
html = render_html_dia(df_dia, fecha_sel)
components.html(html, height=760, scrolling=True)

# Descarga HTML del día (NOMBRE LARGO solicitado)
html_name = f'Linea_de_Tiempo_{_fmt(fecha_sel)}_Suite_Go_Mapper.html'
buf_html = io.BytesIO(html.encode("utf-8"))
st.download_button("⬇️ Descargar HTML del día", data=buf_html, file_name=html_name, mime="text/html")

# Descarga PDF del día (Landscape)
try:
    pdf_bytes = timeline_pdf_bytes(df_dia, fecha_sel)
    pdf_name = f'Linea_de_Tiempo_{_fmt(fecha_sel)}_Suite_Go_Mapper.pdf'
    st.download_button("⬇️ Descargar PDF del día", data=pdf_bytes, file_name=pdf_name, mime="application/pdf")
except Exception as e:
    st.warning(f"No pude generar el PDF: {e}")

# -------- Descarga ZIP (persistente en sesión) --------
import hashlib
zip_signature = (hashlib.sha256(archivo.getvalue()).hexdigest(), tuple(tipos_on))
if st.session_state.get("gm_timeline_zip_signature") != zip_signature:
    st.session_state["zip_bytes"] = None
    st.session_state["gm_timeline_zip_signature"] = zip_signature

st.divider()
st.subheader("Descargas masivas")
if st.button("⚙️ Generar ZIP (todos los días, filtros actuales)"):
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for d in sorted(evdf["Fecha"].unique()):
            day_df = evdf[(evdf["Fecha"]==d) & (evdf["TipoMain"].isin(tipos_on))]
            h = render_html_dia(day_df, d)
            zf.writestr(f'Linea_de_Tiempo_{_fmt(d)}_Suite_Go_Mapper.html', h)
    zip_buf.seek(0)
    st.session_state["zip_bytes"] = zip_buf.read()

if st.session_state["zip_bytes"] is not None:
    st.download_button(
        "⬇️ Descargar ZIP",
        data=st.session_state["zip_bytes"],
        file_name="Lineas de Tiempo - Suite Go Mapper.zip",
        mime="application/zip"
    )
