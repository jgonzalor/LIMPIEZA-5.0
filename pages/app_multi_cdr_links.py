# pages/app_multi_cdr_links.py
# 🔗 Análisis Multi-CDR entre titulares
#
# - Sube entre 2 y 5 CDR LIMPIOS (los Excel que salen de Limpieza/Compilador).
# - Cada archivo debe tener al menos: Teléfono, Número A, Número B.
# - "Teléfono" = titular de esa CDR (línea investigada).
# - Construye un grafo tipo Link Analysis:
#     * Nodos grandes: titulares de cada CDR.
#     * Nodos secundarios: números que aparecen en 2+ CDR
#       o que se comunican con 2+ titulares.
#     * Aristas: comunicación entre esos nodos.
# - Tooltip en cada vínculo: #eventos, voz, SMS, minutos, rango de fechas.
# - Permite descargar en Excel TODOS los registros de un vínculo seleccionado.

import re
import math
from io import BytesIO
from datetime import datetime
from typing import Dict, List, Tuple, Set

import numpy as np
import pandas as pd
import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")
import streamlit.components.v1 as components

# 🔐 Guardián central y navegación de la suite
from guardian import login_guard
from suite_nav import render_suite_sidebar

# Grafo interactivo
try:
    from pyvis.network import Network
except ModuleNotFoundError:
    Network = None  # type: ignore


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _normalize_msisdn(x) -> str | None:
    """Normaliza números telefónicos a una cadena estable."""
    if pd.isna(x):
        return None
    s = str(x).strip()

    if not s or s.lower() in ("nan", "none"):
        return None

    # Quitar ".0" típico de Excel
    if s.endswith(".0"):
        s = s[:-2]

    # Dejar sólo dígitos y posible + inicial
    s = re.sub(r"[^\d+]", "", s)

    if not s:
        return None
    return s


def _load_cdr_excel(uploaded_file, cdr_label: str) -> pd.DataFrame | None:
    """Lee el CDR desde Excel, buscando una hoja de datos limpia."""
    try:
        xls = pd.ExcelFile(uploaded_file)
    except Exception as e:
        st.error(f"❌ No se pudo leer el archivo {uploaded_file.name}: {e}")
        return None

    # Preferir hoja que contenga "DATOS_LIM" o "DATOS" en el nombre
    sheet_name = None
    for name in xls.sheet_names:
        low = name.lower()
        if "datos_limp" in low or "datos" in low:
            sheet_name = name
            break

    if sheet_name is None:
        sheet_name = xls.sheet_names[0]

    try:
        df = pd.read_excel(xls, sheet_name=sheet_name)
    except Exception as e:
        st.error(f"❌ No se pudo leer la hoja '{sheet_name}' en {uploaded_file.name}: {e}")
        return None

    required_cols = ["Teléfono", "Número A", "Número B"]
    faltan = [c for c in required_cols if c not in df.columns]
    if faltan:
        st.error(
            f"❌ En el archivo {uploaded_file.name} (hoja '{sheet_name}') "
            f"faltan las columnas obligatorias: {', '.join(faltan)}"
        )
        return None

    df["_CDR_LABEL"] = cdr_label
    return df


def _ensure_datetime(df: pd.DataFrame) -> pd.Series:
    """Devuelve una serie Datetime a partir de columnas típicas."""
    if "Datetime" in df.columns:
        dt = pd.to_datetime(df["Datetime"], errors="coerce")
        return dt

    if "Fecha" in df.columns and "Hora" in df.columns:
        combo = df["Fecha"].astype(str) + " " + df["Hora"].astype(str)
        dt = pd.to_datetime(combo, errors="coerce", dayfirst=True)
        return dt

    if "Fecha" in df.columns:
        dt = pd.to_datetime(df["Fecha"], errors="coerce", dayfirst=True)
        return dt

    # Si no hay nada, devolvemos todo NaT
    return pd.to_datetime(pd.Series([pd.NaT] * len(df)))


def _clasifica_tipo(tipo_val) -> str:
    """Clasifica el tipo en VOZ / SMS / OTRO para el resumen."""
    if pd.isna(tipo_val):
        return "OTRO"
    s = str(tipo_val).upper()
    if "VOZ" in s or "LLAM" in s:
        return "VOZ"
    if "SMS" in s or "MENSA" in s or "TEXTO" in s:
        return "SMS"
    return "OTRO"


# ----------------------------------------------------------------------
# Lógica principal de construcción de nodos y vínculos
# ----------------------------------------------------------------------
def construir_grafo_multi_cdr(
    df_all: pd.DataFrame,
    titulares_info: List[Dict[str, str]],
) -> tuple[pd.DataFrame, dict, set, set, dict]:
    """
    A partir del DataFrame unificado y la info de titulares,
    construye:

    - edges_summary: DataFrame de vínculos agregados.
    - edge_details: dict[(u, v)] -> DataFrame de registros brutos.
    - titulares_set: set de MSISDN titulares.
    - bridge_numbers: set de números "puente".
    - node_meta: dict[num] -> metadata (tipo, cdr_count, titular_count).
    """
    # Normalizar números A/B
    df_all = df_all.copy()
    df_all["A_norm"] = df_all["Número A"].apply(_normalize_msisdn)
    df_all["B_norm"] = df_all["Número B"].apply(_normalize_msisdn)
    df_all["_Datetime"] = _ensure_datetime(df_all)
    df_all["_tipo_simple"] = df_all.get("Tipo", np.nan).apply(_clasifica_tipo)

    df_all = df_all.dropna(subset=["A_norm", "B_norm"])

    # Conjunto de titulares
    titulares_set: Set[str] = set()
    titular_to_cdrs: dict[str, List[str]] = {}

    for info in titulares_info:
        titular = info["titular_msisdn"]
        cdr_label = info["cdr_label"]
        if titular:
            titulares_set.add(titular)
            titular_to_cdrs.setdefault(titular, []).append(cdr_label)

    # Cuántas CDR distintas aparece cada número (A o B)
    flat_nodes = pd.concat(
        [
            df_all[["_CDR_LABEL", "A_norm"]].rename(columns={"A_norm": "msisdn"}),
            df_all[["_CDR_LABEL", "B_norm"]].rename(columns={"B_norm": "msisdn"}),
        ],
        ignore_index=True,
    )
    flat_nodes = flat_nodes.dropna(subset=["msisdn"])
    cdr_counts = flat_nodes.groupby("msisdn")["_CDR_LABEL"].nunique()

    # Con qué titulares se comunica cada número
    contactos_rows = []

    tmp = df_all[["A_norm", "B_norm"]].copy()
    # A -> B (B es titular)
    tmp1 = tmp[tmp["B_norm"].isin(titulares_set)].copy()
    tmp1.rename(columns={"A_norm": "msisdn", "B_norm": "titular"}, inplace=True)

    # B -> A (A es titular)
    tmp2 = tmp[tmp["A_norm"].isin(titulares_set)].copy()
    tmp2.rename(columns={"B_norm": "msisdn", "A_norm": "titular"}, inplace=True)

    contactos_rows.append(tmp1[["msisdn", "titular"]])
    contactos_rows.append(tmp2[["msisdn", "titular"]])

    df_talk = pd.concat(contactos_rows, ignore_index=True).dropna()
    titular_counts = df_talk.groupby("msisdn")["titular"].nunique()

    # Números "puente":
    #  - aparecen en 2+ CDR, o
    #  - se comunican con 2+ titulares
    bridge_numbers: Set[str] = set()
    for num in cdr_counts.index:
        if num in titulares_set:
            continue
        if cdr_counts.get(num, 0) >= 2 or titular_counts.get(num, 0) >= 2:
            bridge_numbers.add(num)

    # Nodos que vamos a mostrar en el grafo
    node_numbers: Set[str] = set(titulares_set) | bridge_numbers

    # Filtrar registros donde ambos extremos son nodos del grafo
    df_edges = df_all[
        df_all["A_norm"].isin(node_numbers) & df_all["B_norm"].isin(node_numbers)
    ].copy()

    if df_edges.empty:
        return (
            pd.DataFrame(),
            {},
            titulares_set,
            bridge_numbers,
            {},
        )

    def edge_key(a: str, b: str) -> tuple[str, str]:
        return tuple(sorted((a, b)))

    df_edges["edge_key"] = df_edges.apply(
        lambda r: edge_key(r["A_norm"], r["B_norm"]), axis=1
    )

    # Agregamos por vínculo
    summary_rows: List[dict] = []
    edge_details: dict[tuple[str, str], pd.DataFrame] = {}

    for ek, sub in df_edges.groupby("edge_key"):
        u, v = ek
        total_events = len(sub)
        voz_events = int((sub["_tipo_simple"] == "VOZ").sum())
        sms_events = int((sub["_tipo_simple"] == "SMS").sum())
        total_secs = (
            pd.to_numeric(sub.get("Duración (seg)", 0), errors="coerce")
            .fillna(0)
            .sum()
        )
        total_min = float(total_secs) / 60.0 if total_secs else 0.0

        first_dt = sub["_Datetime"].min()
        last_dt = sub["_Datetime"].max()

        if pd.isna(first_dt) or pd.isna(last_dt):
            date_range = "sin fecha"
        else:
            date_range = f"{first_dt.strftime('%Y-%m-%d')} a {last_dt.strftime('%Y-%m-%d')}"

        tooltip = (
            f"{total_events} eventos · {voz_events} voz · {sms_events} SMS · "
            f"{total_min:.1f} min · {date_range}"
        )
        label = f"{u} ↔ {v}"

        summary_rows.append(
            {
                "edge_key": ek,
                "De": u,
                "Hacia": v,
                "Eventos totales": total_events,
                "Voz": voz_events,
                "SMS": sms_events,
                "Minutos totales": round(total_min, 1),
                "Fecha inicial": first_dt,
                "Fecha final": last_dt,
                "Tooltip": tooltip,
                "Etiqueta vínculo": label,
            }
        )

        edge_details[ek] = sub

    edges_summary = pd.DataFrame(summary_rows).sort_values(
        "Eventos totales", ascending=False
    )

    # Metadata de nodos (para el grafo)
    node_meta: dict[str, dict] = {}

    for num in node_numbers:
        node_meta[num] = {
            "tipo": "titular" if num in titulares_set else "puente",
            "cdr_count": int(cdr_counts.get(num, 0)),
            "titular_count": int(titular_counts.get(num, 0)),
            "cdr_labels": [],
        }

    for titular, cdr_list in titular_to_cdrs.items():
        if titular in node_meta:
            node_meta[titular]["cdr_labels"] = cdr_list

    return edges_summary, edge_details, titulares_set, bridge_numbers, node_meta


def _exportar_excel_detalle(df: pd.DataFrame, filename: str) -> BytesIO:
    """Prepara un Excel en memoria para descarga."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Detalle_vinculo")
    output.seek(0)
    return output


# ----------------------------------------------------------------------
# APP
# ----------------------------------------------------------------------
def main():
    # --- Guardián de acceso a la suite ---
    login_guard()
    render_suite_sidebar()

    st.title("🔗 Análisis Multi-CDR entre titulares")
    st.caption(
        "Sube varias CDR limpias (3–5 sabanas) y visualiza cómo se conectan "
        "los titulares y los números puente entre ellas."
    )

    uploaded_files = st.file_uploader(
        "📂 Sube entre 2 y 5 CDR limpios (Excel)",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
    )

    if not uploaded_files:
        st.info("Sube al menos 2 CDR para comenzar el análisis.")
        return

    if len(uploaded_files) < 2:
        st.warning("Necesitas al menos 2 CDR para comparar.")
        return

    if len(uploaded_files) > 5:
        st.warning("Por ahora el módulo soporta máximo 5 CDR. Toma los más relevantes.")
        return

    # ------------------------------------------------------------------
    # Carga de CDR y detección de titulares
    # ------------------------------------------------------------------
    st.subheader("1️⃣ Carga de CDR y titulares")

    cdr_frames: List[pd.DataFrame] = []
    titulares_info: List[Dict[str, str]] = []

    for idx, up in enumerate(uploaded_files):
        cdr_label = f"CDR {idx + 1}"
        df = _load_cdr_excel(up, cdr_label)
        if df is None:
            return

        # Titular = primer valor de la columna 'Teléfono'
        titular_raw = df["Teléfono"].iloc[0]
        titular_norm = _normalize_msisdn(titular_raw)

        if not titular_norm:
            st.error(
                f"❌ En el archivo {up.name}, la columna 'Teléfono' no tiene un "
                f"titular válido en la primera fila."
            )
            return

        titulares_info.append(
            {
                "cdr_label": cdr_label,
                "filename": up.name,
                "titular_msisdn": titular_norm,
            }
        )

        cdr_frames.append(df)

    df_all = pd.concat(cdr_frames, ignore_index=True)

    # Mostrar resumen de titulares
    resumen_titulares = pd.DataFrame(
        [
            {
                "CDR": info["cdr_label"],
                "Archivo": info["filename"],
                "Titular (Teléfono)": info["titular_msisdn"],
            }
            for info in titulares_info
        ]
    )
    st.dataframe(resumen_titulares, use_container_width=True)

    st.subheader("2️⃣ Construcción de vínculos entre CDR")

    with st.spinner("Analizando vínculos entre titulares y números puente..."):
        (
            edges_summary,
            edge_details,
            titulares_set,
            bridge_numbers,
            node_meta,
        ) = construir_grafo_multi_cdr(df_all, titulares_info)

    if edges_summary.empty:
        st.warning(
            "No se encontraron vínculos entre titulares y números que aparezcan en "
            "2+ CDR o se comuniquen con 2+ titulares. "
            "Prueba con otras CDR o revisa que los datos estén limpios."
        )
        return

    st.success(
        f"Se detectaron {len(titulares_set)} titulares y "
        f"{len(bridge_numbers)} números puente relevantes."
    )

    # Filtro mínimo de eventos por vínculo
    max_eventos = int(edges_summary["Eventos totales"].max())
    min_eventos = st.slider(
        "Mínimo de eventos para mostrar un vínculo:",
        min_value=1,
        max_value=max_eventos if max_eventos > 1 else 1,
        value=1,
    )

    edges_filtered = edges_summary[
        edges_summary["Eventos totales"] >= min_eventos
    ].copy()

    if edges_filtered.empty:
        st.warning(
            f"No hay vínculos con al menos {min_eventos} eventos. "
            f"Reduce el filtro para ver resultados."
        )
        return

    # ------------------------------------------------------------------
    # 3) Grafo interactivo
    # ------------------------------------------------------------------
    st.subheader("3️⃣ Grafo de vínculos (titulares y números puente)")

    layout_mode = st.radio(
        "Tipo de layout del grafo:",
        ["Automático (fuerzas)", "Circular"],
        index=0,
        help="Elige 'Circular' para ver todos los nodos distribuidos en un círculo.",
    )

    if Network is None:
        st.error(
            "pyvis no está instalado en el entorno, por lo que no se puede "
            "renderizar el grafo. Instala 'pyvis' en tu ambiente."
        )
    else:
        net = Network(
            height="650px",
            width="100%",
            bgcolor="#0E1117",
            font_color="#FFFFFF",
            notebook=False,
            directed=False,
        )

        if layout_mode == "Automático (fuerzas)":
            net.barnes_hut()
        else:
            net.toggle_physics(False)

        # Precalcular posiciones para layout circular
        positions = {}
        if layout_mode == "Circular":
            node_ids = list(node_meta.keys())
            n_nodes = len(node_ids)
            radius = 300
            if n_nodes > 0:
                for i, nid in enumerate(node_ids):
                    angle = 2 * math.pi * i / n_nodes
                    x = radius * math.cos(angle)
                    y = radius * math.sin(angle)
                    positions[nid] = (x, y)

        # Nodos
        for num, meta in node_meta.items():
            tipo = meta["tipo"]
            cdr_count = meta["cdr_count"]
            titular_count = meta["titular_count"]
            cdr_labels = meta.get("cdr_labels", [])

            if tipo == "titular":
                etiqueta_cdr = ", ".join(cdr_labels) if cdr_labels else ""
                label = num
                title_lines = [f"TITULAR: {num}"]
                if etiqueta_cdr:
                    title_lines.append(f"CDR: {etiqueta_cdr}")
                title_lines.append(f"Aparece en {cdr_count} CDR")
                title = "<br>".join(title_lines)

                if layout_mode == "Circular":
                    x, y = positions.get(num, (0, 0))
                    net.add_node(
                        num,
                        label=label,
                        title=title,
                        color="#e74c3c",
                        shape="dot",
                        size=32,
                        x=x,
                        y=y,
                        physics=False,
                    )
                else:
                    net.add_node(
                        num,
                        label=label,
                        title=title,
                        color="#e74c3c",
                        shape="dot",
                        size=32,
                    )
            else:
                title_lines = [
                    f"Número puente: {num}",
                    f"Aparece en {cdr_count} CDR",
                    f"Se comunica con {titular_count} titulares",
                ]
                title = "<br>".join(title_lines)

                if layout_mode == "Circular":
                    x, y = positions.get(num, (0, 0))
                    net.add_node(
                        num,
                        label=num,
                        title=title,
                        color="#3498db",
                        shape="dot",
                        size=18,
                        x=x,
                        y=y,
                        physics=False,
                    )
                else:
                    net.add_node(
                        num,
                        label=num,
                        title=title,
                        color="#3498db",
                        shape="dot",
                        size=18,
                    )

        # Aristas
        for _, row in edges_filtered.iterrows():
            u = row["De"]
            v = row["Hacia"]
            tooltip = row["Tooltip"]
            value = int(row["Eventos totales"])
            net.add_edge(u, v, title=tooltip, value=value)

        html_file = "multi_cdr_links_graph.html"
        net.save_graph(html_file)
        with open(html_file, "r", encoding="utf-8") as f:
            html = f.read()
        components.html(html, height=700, scrolling=True)

    # ------------------------------------------------------------------
    # 4) Tabla de vínculos + descarga de detalle
    # ------------------------------------------------------------------
    st.subheader("4️⃣ Resumen de vínculos y detalle por vínculo")

    st.markdown(
        "La tabla muestra cada vínculo entre nodos (titulares y números puente). "
        "Selecciona uno para ver TODOS los registros de ese vínculo y descargarlo en Excel."
    )

    st.dataframe(
                edges_filtered[
            [
                "Etiqueta vínculo",
                "Eventos totales",
                "Voz",
                "SMS",
                "Minutos totales",
                "Fecha inicial",
                "Fecha final",
            ]
        ],
        use_container_width=True,
    )

    edge_labels = edges_filtered["Etiqueta vínculo"].tolist()
    selected_label = st.selectbox(
        "Selecciona un vínculo para ver el detalle completo:",
        options=edge_labels,
    )

    if selected_label:
        fila = edges_filtered[edges_filtered["Etiqueta vínculo"] == selected_label].iloc[
            0
        ]
        ek = fila["edge_key"]  # (u, v)
        detalle_df = edge_details[ek].copy()

        # Reordenar columnas: primero lo más útil
        prioridad = [
            "_CDR_LABEL",
            "Teléfono",
            "Número A",
            "Número B",
            "Tipo",
            "Fecha",
            "Hora",
            "Duración (seg)",
            "Latitud",
            "Longitud",
            "PLUS_CODE_NOMBRE",
            "_Datetime",
        ]
        cols_existentes = [c for c in prioridad if c in detalle_df.columns]
        otras = [c for c in detalle_df.columns if c not in cols_existentes]
        detalle_df = detalle_df[cols_existentes + otras]

        st.markdown("#### Detalle de registros del vínculo seleccionado")
        st.dataframe(detalle_df, use_container_width=True)

        # Descargar Excel con todos los registros de ese vínculo
        safe_label = selected_label.replace(" ", "_").replace("↔", "-")
        excel_bytes = _exportar_excel_detalle(
            detalle_df, filename=f"detalle_vinculo_{safe_label}.xlsx"
        )

        st.download_button(
            "📥 Descargar detalle en Excel",
            data=excel_bytes,
            file_name=f"detalle_vinculo_{safe_label}.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )


if __name__ == "__main__":
    main()
