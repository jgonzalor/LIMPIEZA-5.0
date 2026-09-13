# pages/app_maestro_ubicaciones.py — Maestro de ubicaciones / PLUS_CODE
import sqlite3
from pathlib import Path
from datetime import datetime
import io

import pandas as pd
import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")
# tus otros imports...

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

# ────────────────────────────────────────────────
# Configuración de página
# ────────────────────────────────────────────────
pass  # Page configuration is initialized before rendering.

st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}

    footer {visibility: hidden;}
    .stButton>button { border-radius: 8px; padding: 0.3rem 0.7rem; }
    .small-text { font-size: 0.8rem; color: #666; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ────────────────────────────────────────────────
# Configuración de la base de datos
# ────────────────────────────────────────────────
# Usamos el mismo archivo que vienes usando para repos de plus:
DB_PATH = Path("plus_repo.sqlite")


def init_db():
    """Crea la tabla maestro_ubicaciones si no existe."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS maestro_ubicaciones (
            plus_code          TEXT PRIMARY KEY,
            lat                REAL,
            lon                REAL,
            direccion_completa TEXT,
            direccion_resumida TEXT,
            fuente             TEXT,
            creado_en          TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def get_conn():
    init_db()
    return sqlite3.connect(DB_PATH)


def contar_registros():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM maestro_ubicaciones;")
    (n,) = cur.fetchone()
    conn.close()
    return n


def cargar_df(filtro: str | None = None) -> pd.DataFrame:
    conn = get_conn()
    base = """
        SELECT plus_code, lat, lon,
               direccion_completa, direccion_resumida,
               fuente, creado_en
        FROM maestro_ubicaciones
    """
    params = []
    if filtro:
        filtro_like = f"%{filtro.strip()}%"
        base += """
            WHERE plus_code LIKE ?
               OR IFNULL(direccion_resumida,'') LIKE ?
               OR IFNULL(direccion_completa,'') LIKE ?
        """
        params = [filtro_like, filtro_like, filtro_like]

    df = pd.read_sql_query(base, conn, params=params)
    conn.close()
    return df


def upsert_ubicacion(
    plus_code: str,
    lat,
    lon,
    direccion_completa: str,
    direccion_resumida: str,
    fuente: str,
):
    plus_code = (plus_code or "").strip().upper()
    if not plus_code:
        raise ValueError("PLUS_CODE vacío")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO maestro_ubicaciones
            (plus_code, lat, lon, direccion_completa, direccion_resumida, fuente, creado_en)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(plus_code) DO UPDATE SET
            lat                = excluded.lat,
            lon                = excluded.lon,
            direccion_completa = excluded.direccion_completa,
            direccion_resumida = excluded.direccion_resumida,
            fuente             = excluded.fuente
        ;
        """,
        (
            plus_code,
            lat if lat is not None else None,
            lon if lon is not None else None,
            (direccion_completa or "").strip(),
            (direccion_resumida or "").strip(),
            (fuente or "").strip(),
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


def eliminar_plus_codes(lista):
    if not lista:
        return 0
    conn = get_conn()
    cur = conn.cursor()
    cur.executemany(
        "DELETE FROM maestro_ubicaciones WHERE plus_code = ?;",
        [(pc,) for pc in lista],
    )
    conn.commit()
    cambios = conn.total_changes
    conn.close()
    return cambios


# ────────────────────────────────────────────────
# UI
# ────────────────────────────────────────────────
from suite_nav import render_suite_sidebar
from ui.components import render_page_header
render_suite_sidebar()
render_page_header("Maestro de ubicaciones", "Catálogo local de coordenadas y direcciones.")
st.caption(
    "Base maestra de ubicaciones para reutilizar en Limpieza / KMZ "
    "sin depender siempre del geocoder."
)

col_info, col_kpi = st.columns([3, 1])
with col_info:
    st.markdown(
        f"**Base de datos:** `{DB_PATH}`  \n"
        "Clave: `plus_code` (en mayúsculas). Campos: lat, lon, "
        "direccion_completa, direccion_resumida, fuente."
    )
with col_kpi:
    st.metric("Registros", contar_registros())

st.markdown("---")

# ────────────────────────────────────────────────
# 1) Carga masiva desde Excel / CSV
# ────────────────────────────────────────────────
st.header("1️⃣ Cargar Excel/CSV con ubicaciones")

archivo = st.file_uploader(
    "Sube un archivo (Excel/CSV). Mínimo debe tener PLUS_CODE. "
    "Opcionales: LAT, LON, DIRECCION_COMPLETA, DIRECCION_RESUMIDA, FUENTE.",
    type=["xlsx", "xls", "csv"],
)

if archivo is not None:
    # Leer archivo
    try:
        if archivo.name.lower().endswith(".csv"):
            df_in = pd.read_csv(archivo)
        else:
            df_in = pd.read_excel(archivo)
    except Exception as e:
        st.error(f"No se pudo leer el archivo: {e}")
        df_in = None

    if df_in is not None and not df_in.empty:
        # Normalizar encabezados a MAYÚSCULAS
        df_in.columns = [str(c).strip().upper() for c in df_in.columns]

        st.write("Vista previa:")
        st.dataframe(df_in.head(), use_container_width=True)

        cols = list(df_in.columns)

        faltan = [c for c in ["PLUS_CODE"] if c not in cols]
        if faltan:
            st.error(
                "El archivo debe contener al menos la columna PLUS_CODE.\n"
                f"Faltan: {', '.join(faltan)}"
            )
        else:
            st.markdown("### Mapeo de columnas")

            col1, col2 = st.columns(2)
            with col1:
                col_plus = st.selectbox(
                    "Columna para PLUS_CODE (obligatoria)",
                    options=cols,
                    index=cols.index("PLUS_CODE") if "PLUS_CODE" in cols else 0,
                )
                col_lat = st.selectbox(
                    "Columna para LAT (opcional)",
                    options=["(ninguna)"] + cols,
                    index=0,
                )
                col_lon = st.selectbox(
                    "Columna para LON (opcional)",
                    options=["(ninguna)"] + cols,
                    index=0,
                )
            with col2:
                col_dir_c = st.selectbox(
                    "Columna para DIRECCION_COMPLETA (opcional)",
                    options=["(ninguna)"] + cols,
                    index=(
                        ["(ninguna)"] + cols
                    ).index("DIRECCION_COMPLETA")
                    if "DIRECCION_COMPLETA" in cols
                    else 0,
                )
                col_dir_r = st.selectbox(
                    "Columna para DIRECCION_RESUMIDA / PLUS_CODE_NOMBRE (opcional)",
                    options=["(ninguna)"] + cols,
                    index=(
                        ["(ninguna)"] + cols
                    ).index("PLUS_CODE_NOMBRE")
                    if "PLUS_CODE_NOMBRE" in cols
                    else 0,
                )
                col_fuente = st.selectbox(
                    "Columna para FUENTE (opcional)",
                    options=["(ninguna)"] + cols,
                    index=(
                        ["(ninguna)"] + cols
                    ).index("FUENTE")
                    if "FUENTE" in cols
                    else 0,
                )

            if st.button("💾 Guardar en maestro_ubicaciones", type="primary"):
                n_ok = 0
                n_err = 0
                errores = []

                for idx, row in df_in.iterrows():
                    try:
                        pc_val = row[col_plus]
                        if pd.isna(pc_val):
                            continue
                        plus_code = str(pc_val).strip()
                        if not plus_code:
                            continue

                        lat_val = None
                        lon_val = None
                        dir_c_val = ""
                        dir_r_val = ""
                        fuente_val = ""

                        if col_lat != "(ninguna)":
                            v = row[col_lat]
                            if pd.notna(v):
                                try:
                                    lat_val = float(v)
                                except Exception:
                                    lat_val = None

                        if col_lon != "(ninguna)":
                            v = row[col_lon]
                            if pd.notna(v):
                                try:
                                    lon_val = float(v)
                                except Exception:
                                    lon_val = None

                        if col_dir_c != "(ninguna)":
                            v = row[col_dir_c]
                            if pd.notna(v):
                                dir_c_val = str(v)

                        if col_dir_r != "(ninguna)":
                            v = row[col_dir_r]
                            if pd.notna(v):
                                dir_r_val = str(v)

                        if col_fuente != "(ninguna)":
                            v = row[col_fuente]
                            if pd.notna(v):
                                fuente_val = str(v)

                        upsert_ubicacion(
                            plus_code=plus_code,
                            lat=lat_val,
                            lon=lon_val,
                            direccion_completa=dir_c_val,
                            direccion_resumida=dir_r_val,
                            fuente=fuente_val or "archivo",
                        )
                        n_ok += 1
                    except Exception as e:
                        n_err += 1
                        if len(errores) < 5:
                            errores.append(f"Fila {idx}: {e}")

                st.success(f"Se guardaron/actualizaron {n_ok} registros en maestro_ubicaciones.")
                if n_err > 0:
                    st.warning(f"{n_err} filas tuvieron errores y se saltaron.")
                    if errores:
                        with st.expander("Ver ejemplos de errores"):
                            for msg in errores:
                                st.text(msg)

                st.experimental_rerun()
else:
    st.info("Sube un archivo para carga masiva, o usa el formulario manual de abajo.")

st.markdown("---")

# ────────────────────────────────────────────────
# 2) Alta / edición manual
# ────────────────────────────────────────────────
st.header("2️⃣ Agregar / editar una ubicación manualmente")

with st.form("form_manual"):
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        pc_in = st.text_input("PLUS_CODE", placeholder="Ej. 75PJRHC6+64")
        dir_res_in = st.text_input(
            "Direccion RESUMIDA (para PLUS_CODE_NOMBRE)",
            placeholder="Ej. Antena Alonso de Ávalos, Culiacán, Sinaloa",
        )
    with c2:
        lat_in = st.text_input("LAT (opcional)", placeholder="Ej. 24.82055556")
        lon_in = st.text_input("LON (opcional)", placeholder="-107.4397222")
    with c3:
        fuente_in = st.text_input(
            "Fuente",
            value="manual",
            help="Ej. 'manual', 'operador', 'archivo_octubre', etc.",
        )

    dir_comp_in = st.text_area(
        "Direccion COMPLETA (opcional)",
        placeholder="Calle, colonia, municipio, estado, CP…",
    )

    submitted = st.form_submit_button("💾 Guardar/actualizar", type="primary")

    if submitted:
        try:
            if not pc_in.strip():
                st.error("Debes capturar al menos el PLUS_CODE.")
            else:
                # Parseo lat/lon
                lat_val = None
                lon_val = None
                if lat_in.strip():
                    try:
                        lat_val = float(lat_in.strip())
                    except Exception:
                        st.warning("No se pudo convertir LAT, se guardará como NULL.")
                if lon_in.strip():
                    try:
                        lon_val = float(lon_in.strip())
                    except Exception:
                        st.warning("No se pudo convertir LON, se guardará como NULL.")

                upsert_ubicacion(
                    plus_code=pc_in,
                    lat=lat_val,
                    lon=lon_val,
                    direccion_completa=dir_comp_in,
                    direccion_resumida=dir_res_in,
                    fuente=fuente_in,
                )
                st.success("Ubicación guardada/actualizada correctamente.")
                st.experimental_rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")

st.markdown("---")

# ────────────────────────────────────────────────
# 3) Consultar / eliminar / exportar
# ────────────────────────────────────────────────
st.header("3️⃣ Consultar / eliminar / exportar")

col_filtro, col_export = st.columns([3, 2])
with col_filtro:
    filtro = st.text_input(
        "Filtro por PLUS_CODE, direccion_resumida o direccion_completa",
        placeholder="Ej. '75PJRH', 'Ávalos', 'Culiacán'…",
    )

df_repo = cargar_df(filtro if filtro else None)

with col_export:
    # Exportar maestro_ubicaciones a Excel
    if not df_repo.empty:
        buffer = io.BytesIO()
        # Usamos openpyxl para evitar depender de xlsxwriter
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df_repo.to_excel(writer, index=False, sheet_name="maestro_ubicaciones")
        buffer.seek(0)
        st.download_button(
            "⬇️ Exportar maestro_ubicaciones a Excel",
            data=buffer,
            file_name="maestro_ubicaciones_export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.caption("Sin datos para exportar.")

    st.write("")  # pequeño espacio

    # Botón para descargar el archivo SQLite completo como respaldo
    if DB_PATH.exists():
        with open(DB_PATH, "rb") as f:
            st.download_button(
                "⬇️ Descargar plus_repo.sqlite (respaldo)",
                data=f.read(),
                file_name="plus_repo.sqlite",
                mime="application/octet-stream",
                help=(
                    "Descarga una copia completa de la base. "
                    "Luego súbela a tu repositorio de GitHub para tener un respaldo."
                ),
            )
    else:
        st.caption("Aún no se ha creado el archivo plus_repo.sqlite en este entorno.")

st.subheader("Registros en maestro_ubicaciones")

if df_repo.empty:
    st.info("No hay registros (o el filtro no encontró coincidencias).")
else:
    st.dataframe(df_repo, use_container_width=True)

    st.markdown("### Eliminar registros")
    lista_plus = df_repo["plus_code"].tolist()
    seleccion = st.multiselect(
        "Selecciona PLUS_CODE a eliminar",
        options=lista_plus,
    )
    col_del1, col_del2 = st.columns([1, 3])
    with col_del1:
        if st.button("🗑️ Eliminar seleccionados", disabled=not seleccion):
            borrados = eliminar_plus_codes(seleccion)
            st.success(f"Se eliminaron {borrados} registros.")
            st.experimental_rerun()
    with col_del2:
        st.markdown(
            '<span class="small-text">Esta acción es permanente, '
            'pero siempre puedes volver a cargar desde Excel.</span>',
            unsafe_allow_html=True,
        )
        st.markdown("### Respaldo de geo_cache.sqlite")

GEO_CACHE_PATH = Path("geo_cache.sqlite")

if GEO_CACHE_PATH.exists():
    with open(GEO_CACHE_PATH, "rb") as f:
        st.download_button(
            "⬇️ Descargar geo_cache.sqlite (respaldo)",
            data=f.read(),
            file_name="geo_cache.sqlite",
            mime="application/octet-stream",
        )
else:
    st.caption("No se encontró geo_cache.sqlite en la raíz del proyecto.")

