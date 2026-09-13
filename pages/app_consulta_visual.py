# pages/app_consulta_visual.py
# 🔍 Consulta visual de CDR (sólo archivos generados por la Suite Limpieza / Lite)

import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")
import pandas as pd
from io import BytesIO

# 🔐 Guardián central de la suite + navegación
from guardian import login_guard
from suite_nav import render_suite_sidebar  # menú lateral de la suite
from ui.styles import apply_theme, kpi_row, page_header, section_title

# tus otros imports...

# --- GUARD DE ACCESO A LA SUITE ---
login_guard()

# --- MENÚ LATERAL DE LA SUITE ---
render_suite_sidebar()

apply_theme()

page_header(
    "Consulta visual de CDR",
    "Explora archivos limpios de la suite con filtros técnicos, tabla operativa y exportación inmediata de resultados.",
    eyebrow="EXPLORACIÓN Y FILTRADO",
    badges=["Mapeo automático", "Filtros por tiempo", "Exportación Excel"],
)

# --------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------

def leer_excel(uploaded_file):
    """Lee un Excel, priorizando la hoja de datos limpios si existe."""
    if uploaded_file is None:
        return None

    try:
        xls = pd.ExcelFile(uploaded_file)
        candidatos_hoja = [
            "DATOS_LIMPIOS",
            "Datos_Limpios",
            "DATOS",
            xls.sheet_names[0],
        ]
        for nombre in candidatos_hoja:
            if nombre in xls.sheet_names:
                return xls.parse(nombre)
        return xls.parse(xls.sheet_names[0])
    except Exception:
        try:
            return pd.read_excel(uploaded_file)
        except Exception:
            return None


def guess_column(df, candidates):
    """Devuelve la primera columna de candidates que exista en df.columns."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


# Candidatos típicos para archivos de la Suite (Limpieza / Lite)
CANDIDATOS = {
    # Línea investigada (Teléfono de referencia, NO es Número A)
    "linea": [
        "Teléfono", "Telefono", "TELÉFONO", "LINEA", "Línea", "Linea",
        "MSISDN"
    ],
    # Número A REAL del CDR
    "num_a": [
        "Número A", "Numero A", "NUM_A", "NUM A", "NUMERO A", "A"
    ],
    # Número B
    "num_b": [
        "Número B", "Numero B", "NUM_B", "NUM B", "NUMERO B", "B",
        "Número_correspondiente", "Numero_correspondiente", "Correspondiente",
        "Teléfono B", "Telefono B"
    ],
    # Tipo de evento
    "tipo": [
        "Tipo", "TIPO", "CALL_TYPE", "EventType", "Tipo evento"
    ],
    # Fecha/hora
    "datetime": [
        "Datetime", "FechaHora", "Fecha_Hora", "Fecha y Hora",
        "Fecha_hora_evento", "FECHA_HORA"
    ],
    # Duración en segundos
    "duracion": [
        "Duración (seg)", "Duracion (seg)", "Duración_seg", "Duracion_seg",
        "DURACION", "CALL_DURATION", "Duración", "Duracion"
    ],
    # Geo
    "lat": [
        "Latitud", "LAT", "lat", "Latitude"
    ],
    "lon": [
        "Longitud", "LON", "lon", "Longitude"
    ],
    # IMEI
    "imei": [
        "IMEI", "IMEI_A", "IMEI (Caller A)"
    ],
}

FRIENDLY = {
    "linea":   "Línea investigada (Teléfono de referencia)",
    "num_a":   "Número A (campo A real del CDR)",
    "num_b":   "Número B (correspondiente / destino)",
    "tipo":    "Tipo de evento",
    "datetime":"Fecha y hora del evento",
    "duracion":"Duración (segundos)",
    "lat":     "Latitud",
    "lon":     "Longitud",
    "imei":    "IMEI",
}


def construir_df_estandar(df):
    """Detecta columnas de la Suite y devuelve df con nombres estándar."""
    mapping = {}
    for campo in CANDIDATOS.keys():
        mapping[campo] = guess_column(df, CANDIDATOS[campo])

    renames = {}

    # Línea investigada como columna aparte
    if mapping.get("linea"):
        renames[mapping["linea"]] = "LINEA"

    # Número A del CDR
    if mapping.get("num_a"):
        renames[mapping["num_a"]] = "NUM_A"

    # Número B
    if mapping.get("num_b"):
        renames[mapping["num_b"]] = "NUM_B"

    # Resto de campos
    if mapping.get("tipo"):
        renames[mapping["tipo"]] = "TIPO"
    if mapping.get("datetime"):
        renames[mapping["datetime"]] = "Datetime"
    if mapping.get("duracion"):
        renames[mapping["duracion"]] = "DURACION"
    if mapping.get("lat"):
        renames[mapping["lat"]] = "LAT"
    if mapping.get("lon"):
        renames[mapping["lon"]] = "LON"
    if mapping.get("imei"):
        renames[mapping["imei"]] = "IMEI"

    df_view = df.rename(columns=renames).copy()

    # Si NO hay NUM_A pero sí LINEA, usamos LINEA como fallback de NUM_A
    if "NUM_A" not in df_view.columns and "LINEA" in df_view.columns:
        df_view["NUM_A"] = df_view["LINEA"]

    # Fallback cruzado A/B para evitar que reviente
    if "NUM_A" not in df_view.columns and "NUM_B" in df_view.columns:
        df_view["NUM_A"] = df_view["NUM_B"]
    if "NUM_B" not in df_view.columns and "NUM_A" in df_view.columns:
        df_view["NUM_B"] = df_view["NUM_A"]

    # Normalizamos fecha/hora
    if "Datetime" in df_view.columns:
        df_view["Datetime"] = pd.to_datetime(
            df_view["Datetime"], errors="coerce", dayfirst=True
        )
        df_view = df_view[~df_view["Datetime"].isna()]

    # Duración a numérico
    if "DURACION" in df_view.columns:
        df_view["DURACION"] = pd.to_numeric(
            df_view["DURACION"], errors="coerce"
        )

    return df_view, mapping


# --------------------------------------------------------------------
# 1) Carga de archivo (o df de sesión)
# --------------------------------------------------------------------

section_title("Cargar datos", "Usa datos de sesión o sube un Excel limpio generado por la suite.", "01")

df = None
origen = None

# Opción A: usar DataFrame de la app de Limpieza (si existe)
if "df_limpio" in st.session_state:
    if st.checkbox("Usar datos de la app de Limpieza (df_limpio en sesión)", value=True):
        df = st.session_state["df_limpio"].copy()
        origen = "sesion"

# Opción B: subir archivo
uploaded_file = st.file_uploader(
    "O bien, sube un archivo Excel generado por la Suite (Limpieza / Lite)",
    type=["xlsx", "xls"],
)

if df is None:
    df = leer_excel(uploaded_file)
    if df is not None and origen is None:
        origen = "archivo"

if df is None:
    st.info("Sube un Excel de la Suite o usa los datos de sesión.")
    st.stop()

st.success(
    f"Datos cargados desde: **{'memoria (df_limpio)' if origen == 'sesion' else 'archivo subido'}**"
)
st.write(f"Columnas detectadas ({len(df.columns)}):", ", ".join(map(str, df.columns)))

# --------------------------------------------------------------------
# 2) Detección automática de campos
# --------------------------------------------------------------------

section_title("Detección automática de campos", "Verifica cómo se homologaron los campos para la vista de consulta.", "02")

df_view, mapping = construir_df_estandar(df)

rows = []
for campo in ["linea", "num_a", "num_b", "tipo", "datetime", "duracion", "lat", "lon", "imei"]:
    desc = FRIENDLY.get(campo, campo)
    col_detectada = mapping.get(campo)
    rows.append(
        {
            "Campo lógico": desc,
            "Columna detectada en el archivo": col_detectada if col_detectada else "— no encontrado —",
        }
    )

st.caption("La app mapeó automáticamente las columnas de tu archivo:")
st.table(pd.DataFrame(rows))

# Mostrar la línea investigada como referencia
if "LINEA" in df_view.columns:
    lineas_unicas = df_view["LINEA"].dropna().astype(str).unique()
    if len(lineas_unicas) == 1:
        st.info(f"📌 Línea investigada (Teléfono): **{lineas_unicas[0]}**")
    elif len(lineas_unicas) > 1:
        st.info(
            f"📌 Se detectaron **{len(lineas_unicas)}** valores distintos en la columna de línea investigada."
        )

# --------------------------------------------------------------------
# 3) Panel de filtros
# --------------------------------------------------------------------

section_title("Filtros", "Acota el universo por número, tipo, rango temporal, duración, IMEI o geolocalización.", "03")

with st.expander("🎛️ Filtros básicos", expanded=True):
    col_a, col_b, col_tipo = st.columns(3)

    # Número A (campo A real)
    if "NUM_A" in df_view.columns:
        with col_a:
            valores_a = sorted(df_view["NUM_A"].dropna().astype(str).unique())
            filtro_a = st.multiselect(
                "📞 Filtrar por Número A (CDR)",
                options=valores_a,
                default=[],
            )
    else:
        filtro_a = []

    # Número B (opciones dependientes de la selección en A)
    if "NUM_B" in df_view.columns:
        with col_b:
            df_para_b = df_view

            # Si hay filtro en A, limitamos NUM_B sólo a los B que tuvieron tráfico con esos A
            if "NUM_A" in df_view.columns and filtro_a:
                df_para_b = df_para_b[df_para_b["NUM_A"].astype(str).isin(filtro_a)]

            valores_b = sorted(df_para_b["NUM_B"].dropna().astype(str).unique())
            filtro_b = st.multiselect(
                "☎️ Filtrar por Número B",
                options=valores_b,
                default=[],
            )
    else:
        filtro_b = []

    # Tipo
    if "TIPO" in df_view.columns:
        with col_tipo:
            tipos = sorted(df_view["TIPO"].dropna().astype(str).unique())
            filtro_tipo = st.multiselect(
                "📂 Tipo de evento",
                options=tipos,
                default=[],
            )
    else:
        filtro_tipo = []


with st.expander("🕒 Filtros por tiempo y duración", expanded=True):
    # Fechas
    if "Datetime" in df_view.columns and not df_view.empty:
        min_dt = df_view["Datetime"].min().date()
        max_dt = df_view["Datetime"].max().date()
        rango_fechas = st.date_input(
            "Rango de fechas (inicio / fin)",
            value=(min_dt, max_dt),
        )
    else:
        rango_fechas = None

    # Duración
    if "DURACION" in df_view.columns and df_view["DURACION"].notna().any():
        dur_min = int(df_view["DURACION"].min())
        dur_max = int(df_view["DURACION"].max())
        filtro_dur_min, filtro_dur_max = st.slider(
            "Duración (segundos)",
            min_value=dur_min,
            max_value=dur_max,
            value=(dur_min, dur_max),
        )
    else:
        filtro_dur_min, filtro_dur_max = None, None


with st.expander("📱 / 📍 Filtros avanzados (IMEI y geolocalización)", expanded=False):
    # IMEI
    if "IMEI" in df_view.columns:
        imeis = sorted(df_view["IMEI"].dropna().astype(str).unique())
        filtro_imei = st.multiselect(
            "📱 IMEI",
            options=imeis,
            default=[],
        )
    else:
        filtro_imei = []

    solo_con_geo = st.checkbox("📍 Solo eventos con latitud/longitud válidas", value=False)


# --------------------------------------------------------------------
# 4) Aplicar filtros
# --------------------------------------------------------------------

df_filtrado = df_view.copy()

# Número A
if filtro_a and "NUM_A" in df_filtrado.columns:
    df_filtrado = df_filtrado[df_filtrado["NUM_A"].astype(str).isin(filtro_a)]

# Número B
if filtro_b and "NUM_B" in df_filtrado.columns:
    df_filtrado = df_filtrado[df_filtrado["NUM_B"].astype(str).isin(filtro_b)]

# Tipo
if filtro_tipo and "TIPO" in df_filtrado.columns:
    df_filtrado = df_filtrado[df_filtrado["TIPO"].astype(str).isin(filtro_tipo)]

# Fechas
if (
    rango_fechas
    and isinstance(rango_fechas, (list, tuple))
    and len(rango_fechas) == 2
    and "Datetime" in df_filtrado.columns
):
    f_ini = pd.to_datetime(rango_fechas[0])
    f_fin = pd.to_datetime(rango_fechas[1]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    df_filtrado = df_filtrado[
        (df_filtrado["Datetime"] >= f_ini) & (df_filtrado["Datetime"] <= f_fin)
    ]

# Duración
if (
    filtro_dur_min is not None
    and filtro_dur_max is not None
    and "DURACION" in df_filtrado.columns
):
    df_filtrado = df_filtrado[
        (df_filtrado["DURACION"] >= filtro_dur_min)
        & (df_filtrado["DURACION"] <= filtro_dur_max)
    ]

# IMEI
if filtro_imei and "IMEI" in df_filtrado.columns:
    df_filtrado = df_filtrado[df_filtrado["IMEI"].astype(str).isin(filtro_imei)]

# Geo
if solo_con_geo and "LAT" in df_filtrado.columns and "LON" in df_filtrado.columns:
    df_filtrado = df_filtrado[df_filtrado["LAT"].notna() & df_filtrado["LON"].notna()]

# Ordenamos por fecha/hora
if "Datetime" in df_filtrado.columns:
    df_filtrado = df_filtrado.sort_values("Datetime")

# --------------------------------------------------------------------
# 5) Resumen + tabla + descarga
# --------------------------------------------------------------------

section_title("Resultado", "Registros filtrados listos para revisión o descarga.", "04")

kpis = [{"label": "Registros filtrados", "value": len(df_filtrado), "help": "Filas que cumplen criterios"}]
if "NUM_B" in df_filtrado.columns:
    kpis.append({"label": "Números B distintos", "value": df_filtrado["NUM_B"].nunique(), "help": "Contrapartes únicas"})
if "Datetime" in df_filtrado.columns and not df_filtrado.empty:
    kpis.append({
        "label": "Rango de fechas",
        "value": f"{df_filtrado['Datetime'].min().date()} → {df_filtrado['Datetime'].max().date()}",
        "help": "Ventana temporal filtrada",
    })
kpi_row(kpis, columns=3)

df_display = df_filtrado.copy()

# Normalizar visualmente teléfonos/IMEI (sin comas ni decimales)
cols_telefonos = ["LINEA", "NUM_A", "NUM_B", "IMEI"]
for col in cols_telefonos:
    if col in df_display.columns:
        df_display[col] = df_display[col].apply(
            lambda x: "" if pd.isna(x) else str(x).replace(",", "").split(".")[0]
        )

st.dataframe(df_display, use_container_width=True, height=500)


@st.cache_data
def to_excel_bytes(df_in):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_in.to_excel(writer, index=False, sheet_name="FILTRO")
    return output.getvalue()


if not df_filtrado.empty:
    excel_bytes = to_excel_bytes(df_filtrado)
    st.download_button(
        label="💾 Descargar resultado filtrado (Excel)",
        data=excel_bytes,
        file_name="cdr_filtrado.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
