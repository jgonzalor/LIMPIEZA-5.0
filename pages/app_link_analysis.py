# pages/app_link_analysis.py
# 🔗 Módulo de Análisis de Vínculos (Link Analysis) para Suite Go Mapper

import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")
import pandas as pd
import numpy as np
import tempfile
import os
from io import BytesIO
import math
import json  # para set_options de pyvis

import streamlit.components.v1 as components

# 🔐 Guardián central de la suite
from guardian import login_guard
from suite_nav import render_suite_sidebar  # menú lateral de la suite
from ui.styles import apply_theme, kpi_row
from ui.components import render_card, render_page_header, render_section, render_step_header

# pyvis para grafo interactivo
try:
    from pyvis.network import Network
except ModuleNotFoundError:
    Network = None  # type: ignore

# networkx / matplotlib para exportar PNG (opcional)
try:
    import networkx as nx  # type: ignore
except ModuleNotFoundError:
    nx = None  # type: ignore

try:
    import matplotlib.pyplot as plt  # type: ignore
except ModuleNotFoundError:
    plt = None  # type: ignore


# =============================
# Utilidades
# =============================

def _guess_col(cols, candidates):
    """Heurística simple para adivinar columnas por nombre."""
    cols_l = [c.lower() for c in cols]
    for cand in candidates:
        for col, col_l in zip(cols, cols_l):
            if cand in col_l:
                return col
    return None


def _normalize_tipo(value: str) -> str:
    """
    Clasifica el tipo de evento en categorías generales:
    - ENTRANTE
    - SALIENTE
    - SMS
    - OTRO
    """
    s = str(value).strip().lower()
    if not s:
        return "OTRO"
    if "sms" in s or "mensaje" in s or "msj" in s or "text" in s:
        return "SMS"
    if "entrante" in s or "incoming" in s:
        return "ENTRANTE"
    if "saliente" in s or "outgoing" in s:
        return "SALIENTE"
    return "OTRO"


def _fmt_dt(dt):
    """Formatea timestamps a 'YYYY-MM-DD HH:MM:SS'."""
    if pd.isna(dt):
        return ""
    try:
        return pd.to_datetime(dt).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(dt)


def _plot_pyvis(net, height=650):
    """Renderiza un grafo de PyVis dentro de Streamlit."""
    try:
        html = net.generate_html(notebook=False)
    except Exception:
        tmp_path = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
        tmp_name = tmp_path.name
        tmp_path.close()
        net.show(tmp_name)
        with open(tmp_name, "r", encoding="utf-8") as f:
            html = f.read()
        os.unlink(tmp_name)
    components.html(html, height=height, scrolling=True)


def _to_excel_bytes(df_excel: pd.DataFrame) -> BytesIO:
    """Convierte un DataFrame a bytes de Excel usando openpyxl."""
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df_excel.to_excel(writer, sheet_name="datos", index=False)
    bio.seek(0)
    return bio


def _build_png_graph(
    df_nodes: pd.DataFrame,
    df_edges: pd.DataFrame,
    numero_objetivo: str,
) -> BytesIO | None:
    """
    Construye una imagen PNG estática del grafo con layout tipo ESTRELLA:
      - Solo vínculos donde participa el número objetivo.
      - Objetivo en el centro, demás en círculo.
      - Colores por tipo (verde ENT, rojo SAL, morado SMS, gris OTRO).
      - Grosor de flecha proporcional al conteo de ese tipo.
    Pensado para ilustrar un dictamen de un abonado específico.
    """
    if nx is None or plt is None:
        return None

    edge_colors_map = {
        "ENTRANTE": "#00AA00",
        "SALIENTE": "#DD0000",
        "SMS": "#800080",
        "OTRO": "#808080",
    }

    numero_objetivo = str(numero_objetivo)

    # --- Nos centramos en vínculos donde participa el objetivo ---
    edges_focus = df_edges[
        (df_edges["n1"].astype(str) == numero_objetivo)
        | (df_edges["n2"].astype(str) == numero_objetivo)
    ].copy()

    # Si no hay, caemos a todos (caso raro)
    if edges_focus.empty:
        edges_focus = df_edges.copy()

    # Conjunto de nodos a dibujar
    nodos_set = set(edges_focus["n1"].astype(str)) | set(
        edges_focus["n2"].astype(str)
    )
    nodos_set.add(numero_objetivo)
    nodos_list = sorted(nodos_set)

    # df_nodes limitado a esos nodos
    df_nodes_focus = df_nodes[df_nodes["numero"].astype(str).isin(nodos_list)].copy()
    if df_nodes_focus.empty:
        df_nodes_focus = pd.DataFrame({"numero": list(nodos_list)})
        df_nodes_focus["total_eventos"] = 1
        df_nodes_focus["grado"] = 0

    # --- Grafo dirigido ---
    G = nx.DiGraph()

    max_total = df_nodes_focus["total_eventos"].max() or 1
    for _, row in df_nodes_focus.iterrows():
        num = str(row["numero"])
        total_ev = float(row.get("total_eventos", 1.0) or 1.0)
        size = 300 + 700 * (total_ev / max_total)
        is_target = num == numero_objetivo
        G.add_node(num, size=size, is_target=is_target)

    # --- Escala de anchos ---
    all_counts: list[int] = []
    for col in ["ENTRANTE", "SALIENTE", "SMS", "OTRO"]:
        if col in edges_focus.columns:
            all_counts.extend(edges_focus[col][edges_focus[col] > 0].tolist())

    if all_counts:
        min_cnt = min(all_counts)
        max_cnt = max(all_counts)
    else:
        min_cnt = max_cnt = None

    def _edge_width(cnt: int) -> float:
        if min_cnt is None or min_cnt == max_cnt:
            return 2.0
        return 1.0 + (cnt - min_cnt) * 9.0 / (max_cnt - min_cnt)

    # --- Aristas: una por tipo con cnt>0 ---
    for _, row in edges_focus.iterrows():
        a = str(row["n1"])
        b = str(row["n2"])
        total_pair = int(row["conteo"])
        for tipo, col_name in [
            ("ENTRANTE", "ENTRANTE"),
            ("SALIENTE", "SALIENTE"),
            ("SMS", "SMS"),
            ("OTRO", "OTRO"),
        ]:
            cnt = int(row.get(col_name, 0) or 0)
            if cnt <= 0:
                continue
            width = _edge_width(cnt)
            color = edge_colors_map.get(tipo, "#808080")
            G.add_edge(
                a,
                b,
                weight=cnt,
                color=color,
                width=width,
                tipo_label=tipo,
                total_pair=total_pair,
            )

    # --- Layout circular tipo estrella ---
    pos: dict[str, tuple[float, float]] = {}
    pos[numero_objetivo] = (0.0, 0.0)

    otros = [n for n in nodos_list if n != numero_objetivo]
    n_otros = len(otros)
    if n_otros > 0:
        radius = 5.0
        for i, n in enumerate(otros):
            angle = 2 * math.pi * i / n_otros
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            pos[n] = (x, y)

    # --- Dibujo ---
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.set_axis_off()

    nodes = list(G.nodes())
    node_sizes = [G.nodes[n]["size"] for n in nodes]
    node_colors = ["#FFD700" if G.nodes[n]["is_target"] else "#97C2FC" for n in nodes]

    edges = list(G.edges())
    edge_colors = [G[u][v]["color"] for u, v in edges]
    edge_widths = [G[u][v]["width"] for u, v in edges]

    nx.draw_networkx_edges(
        G,
        pos,
        ax=ax,
        edge_color=edge_colors,
        width=edge_widths,
        arrows=True,
        arrowstyle="-|>",
        connectionstyle="arc3,rad=0.0",  # rectas
    )
    nx.draw_networkx_nodes(
        G,
        pos,
        ax=ax,
        node_size=node_sizes,
        node_color=node_colors,
    )
    nx.draw_networkx_labels(G, pos, ax=ax, font_size=8)

    buf = BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


# =============================
# MAIN
# =============================

def main():
    # 🔐 Guardián de acceso (centralizado en guardian.py)
    login_guard("Análisis de vínculos")

    # Menú lateral de la Suite Go Mapper
    render_suite_sidebar()
    apply_theme()

    render_page_header(
        "Análisis de vínculos",
        "Construye grafos dirigidos de relaciones A/B con métricas de grado, volumen y evidencia tabular auxiliar.",
        status="ANÁLISIS DE RED",
        tags=["PyVis", "Top contactos", "Exportables"],
    )

    if Network is None:
        st.error(
            "Falta instalar la librería `pyvis` para mostrar el grafo interactivo.\n\n"
            "Agrega la línea `pyvis==0.3.2` a tu archivo `requirements.txt`, "
            "sube los cambios a GitHub y vuelve a cargar la app."
        )
        return

    # -------------------------
    # 1) Origen de los datos
    # -------------------------
    df_session = st.session_state.get("df_limpio")

    opciones_origen = []
    if df_session is not None:
        opciones_origen.append("Usar datos limpios de la Suite (df_limpio)")
    opciones_origen.append("Subir archivo Excel")

    with render_card():
        render_step_header("01", "Filtros / origen", "Selecciona el origen del CDR y controla el universo antes de crear el grafo.")
        origen = st.radio(
            "Origen de los datos",
            opciones_origen,
            horizontal=True,
            key="link_origen_datos",
        )

        df = None
        if origen == "Usar datos limpios de la Suite (df_limpio)":
            df = df_session.copy()
        else:
            archivo = st.file_uploader(
                "Sube un archivo de Excel ya limpio / armonizado",
                type=["xlsx", "xls"],
            )
            if archivo is not None:
                try:
                    df = pd.read_excel(archivo)
                except Exception as e:
                    st.error(f"No pude leer el Excel: {e}")
                    return

    if df is None:
        st.info(
            "Carga un Excel limpio o entra desde la página de Limpieza para usar `df_limpio`."
        )
        return

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    with st.expander("Ver primeras filas de la tabla base"):
        st.dataframe(df.head(50), use_container_width=True)

    # -------------------------
    # 2) Mapeo de columnas
    # -------------------------
    col_numA_guess = _guess_col(
        df.columns,
        ["numero a", "número a", "num a", "num_a", "origen", "caller", "llamante"],
    )
    col_numB_guess = _guess_col(
        df.columns,
        ["numero b", "número b", "num b", "num_b", "destino", "called", "receptor"],
    )
    col_fecha_guess = _guess_col(
        df.columns,
        ["datetime", "fecha_hora", "fecha hora", "fechahora", "fecha", "f_evento"],
    )
    col_tipo_guess = _guess_col(
        df.columns,
        ["tipo", "t_reg", "servicio", "evento"],
    )
    col_dur_guess = _guess_col(
        df.columns,
        ["duracion_seg", "duración_seg", "duracion", "duración", "segundos"],
    )

    auto_ok = (
        col_numA_guess in df.columns
        and col_numB_guess in df.columns
    )

    render_section("Columnas", "Mapeo de columnas clave para construir relaciones A/B.", "02")

    if auto_ok:
        col_numA = col_numA_guess
        col_numB = col_numB_guess
        col_fecha = col_fecha_guess if col_fecha_guess in df.columns else None
        col_tipo = col_tipo_guess if col_tipo_guess in df.columns else None
        col_dur = col_dur_guess if col_dur_guess in df.columns else None

        with st.expander("Mapeo de columnas (detectado automáticamente)", expanded=False):
            st.markdown(
                f"- Número A: **{col_numA}**  \n"
                f"- Número B: **{col_numB}**  \n"
                f"- Fecha/hora: **{col_fecha}**  \n"
                f"- Tipo: **{col_tipo}**  \n"
                f"- Duración: **{col_dur}**"
            )
    else:
        # Mapeo manual solo cuando la detección automática no fue suficiente.
        c1, c2, c3 = st.columns(3)

        with c1:
            col_numA = st.selectbox(
                "Columna Número A (origen / abonado analizado)",
                options=df.columns,
                index=(
                    df.columns.get_loc(col_numA_guess)
                    if col_numA_guess in df.columns
                    else 0
                ),
            )

        with c2:
            col_numB = st.selectbox(
                "Columna Número B (destino / contacto)",
                options=df.columns,
                index=(
                    df.columns.get_loc(col_numB_guess)
                    if col_numB_guess in df.columns
                    else 0
                ),
            )

        with c3:
            if col_fecha_guess and col_fecha_guess in df.columns:
                col_fecha = st.selectbox(
                    "Columna de fecha/hora (opcional, para filtros)",
                    options=["(Sin usar fecha/hora)"] + list(df.columns),
                    index=df.columns.get_loc(col_fecha_guess) + 1,
                )
            else:
                col_fecha = st.selectbox(
                    "Columna de fecha/hora (opcional, para filtros)",
                    options=["(Sin usar fecha/hora)"] + list(df.columns),
                    index=0,
                )

        c4, c5 = st.columns(2)
        with c4:
            col_tipo = st.selectbox(
                "Columna de tipo de evento (VOZ, SMS, DATOS...) (opcional)",
                options=["(Sin tipo)"] + list(df.columns),
                index=(
                    df.columns.get_loc(col_tipo_guess) + 1
                    if col_tipo_guess in df.columns
                    else 0
                ),
            )
        with c5:
            col_dur = st.selectbox(
                "Columna de duración (segundos) (opcional)",
                options=["(Sin duración)"] + list(df.columns),
                index=(
                    df.columns.get_loc(col_dur_guess) + 1
                    if col_dur_guess in df.columns
                    else 0
                ),
            )

        if col_fecha == "(Sin usar fecha/hora)":
            col_fecha = None
        if col_tipo == "(Sin tipo)":
            col_tipo = None
        if col_dur == "(Sin duración)":
            col_dur = None

    # -------------------------
    # 3) Filtros básicos
    # -------------------------
    with render_card():
        render_step_header("03", "Filtros", "Ajusta densidad, periodo y tipos de evento antes de construir la red.")

        if col_fecha:
            df[col_fecha] = pd.to_datetime(df[col_fecha], errors="coerce")

        filtros_col1, filtros_col2, filtros_col3 = st.columns(3)

        with filtros_col1:
            st.markdown("**Modo de grafo:** dirigido según quién llama a quién")

        with filtros_col2:
            max_nodos = st.slider(
                "Máximo de nodos a mostrar en el grafo",
                min_value=10,
                max_value=300,
                value=80,
                step=10,
                help="Para evitar que el grafo se vuelva inmanejable en CDR muy grandes.",
            )

        with filtros_col3:
            min_llamadas = st.slider(
                "Mínimo de eventos totales por vínculo",
                min_value=1,
                max_value=50,
                value=1,
                step=1,
                help="Solo se dibujan enlaces con al menos este número de eventos (sumando todos los tipos).",
            )

    # Filtro por fecha
    if col_fecha:
        df_valid_fecha = df[df[col_fecha].notna()]
        if not df_valid_fecha.empty:
            min_date = df_valid_fecha[col_fecha].dt.date.min()
            max_date = df_valid_fecha[col_fecha].dt.date.max()
            rango = st.date_input(
                "Rango de fechas (para limitar el grafo)",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
            )
            if isinstance(rango, tuple) and len(rango) == 2:
                ini, fin = rango
                mask_fecha = (df[col_fecha].dt.date >= ini) & (
                    df[col_fecha].dt.date <= fin
                )
                df = df[mask_fecha]

    # Filtro por tipo de evento
    if col_tipo:
        tipos_disponibles = sorted(df[col_tipo].dropna().astype(str).unique())
        tipos_sel = st.multiselect(
            "Filtrar por tipo de evento",
            options=tipos_disponibles,
            default=tipos_disponibles,
        )
        if tipos_sel:
            df = df[df[col_tipo].astype(str).isin(tipos_sel)]

    # -------------------------
    # 4) Construcción de vínculos dirigidos
    # -------------------------
    columnas_usar = [col_numA, col_numB]
    if col_dur:
        columnas_usar.append(col_dur)
    if col_fecha:
        columnas_usar.append(col_fecha)
    if col_tipo:
        columnas_usar.append(col_tipo)

    df_v = df[columnas_usar].copy()
    df_v[col_numA] = df_v[col_numA].astype(str).str.strip()
    df_v[col_numB] = df_v[col_numB].astype(str).str.strip()

    # Quitamos vacíos y auto-llamadas
    df_v = df_v[(df_v[col_numA] != "") & (df_v[col_numB] != "")]
    df_v = df_v[df_v[col_numA] != df_v[col_numB]]

    if df_v.empty:
        st.warning("Después de los filtros no quedó ninguna relación A–B para graficar.")
        return

    if col_dur:
        df_v["duracion_seg"] = pd.to_numeric(df_v[col_dur], errors="coerce")
    if col_fecha:
        df_v["fecha_evento"] = pd.to_datetime(df_v[col_fecha], errors="coerce")

    # Dirección real de la llamada: origen/destino en función del tipo
    df_v["origen"] = df_v[col_numA]
    df_v["destino"] = df_v[col_numB]

    if col_tipo:
        df_v["tipo_norm"] = df_v[col_tipo].astype(str).apply(_normalize_tipo)
        # Para llamadas entrantes, invertimos la dirección: otro → abonado
        mask_ent = df_v["tipo_norm"] == "ENTRANTE"
        df_v.loc[mask_ent, "origen"] = df_v.loc[mask_ent, col_numB].values
        df_v.loc[mask_ent, "destino"] = df_v.loc[mask_ent, col_numA].values
    else:
        df_v["tipo_norm"] = "OTRO"

    # Agregación por par origen–destino
    agg_dict = {"conteo": ("origen", "size")}
    if "duracion_seg" in df_v.columns:
        agg_dict["duracion_total_seg"] = ("duracion_seg", "sum")
    if "fecha_evento" in df_v.columns:
        agg_dict["primera_fecha"] = ("fecha_evento", "min")
        agg_dict["ultima_fecha"] = ("fecha_evento", "max")

    df_edges = df_v.groupby(["origen", "destino"]).agg(**agg_dict).reset_index()

    # Conteos por tipo
    tipo_counts = (
        df_v.groupby(["origen", "destino", "tipo_norm"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    df_edges = df_edges.merge(tipo_counts, on=["origen", "destino"], how="left")

    # Aseguramos columnas de tipos
    for c in ["ENTRANTE", "SALIENTE", "SMS", "OTRO"]:
        if c not in df_edges.columns:
            df_edges[c] = 0
        df_edges[c] = df_edges[c].fillna(0).astype(int)

    # Filtro por peso mínimo total
    df_edges = df_edges[df_edges["conteo"] >= min_llamadas]
    if df_edges.empty:
        st.warning("No hay vínculos que cumplan con el mínimo de eventos seleccionado.")
        return

    # Renombramos para uso posterior
    df_edges = df_edges.rename(columns={"origen": "n1", "destino": "n2"})

    # -------------------------
    # 5) Métricas de nodos
    # -------------------------
    s_origen = df_edges.groupby("n1")["conteo"].sum()
    s_destino = df_edges.groupby("n2")["conteo"].sum()
    total_eventos = s_origen.add(s_destino, fill_value=0)

    deg_origen = df_edges.groupby("n1")["n2"].nunique()
    deg_destino = df_edges.groupby("n2")["n1"].nunique()
    grado = deg_origen.add(deg_destino, fill_value=0).astype(int)

    df_nodes = (
        pd.DataFrame(
            {
                "numero": total_eventos.index,
                "total_eventos": total_eventos.values,
            }
        )
        .merge(
            grado.rename("grado"),
            left_on="numero",
            right_index=True,
            how="left",
        )
        .fillna({"grado": 0})
    )
    df_nodes["grado"] = df_nodes["grado"].astype(int)
    df_nodes = df_nodes.sort_values("total_eventos", ascending=False)

    # Rango temporal por nodo (si hay fechas)
    if "primera_fecha" in df_edges.columns and "ultima_fecha" in df_edges.columns:
        min_n1 = df_edges.groupby("n1")["primera_fecha"].min()
        min_n2 = df_edges.groupby("n2")["primera_fecha"].min()
        max_n1 = df_edges.groupby("n1")["ultima_fecha"].max()
        max_n2 = df_edges.groupby("n2")["ultima_fecha"].max()

        primera_nodo = pd.concat([min_n1, min_n2]).groupby(level=0).min()
        ultima_nodo = pd.concat([max_n1, max_n2]).groupby(level=0).max()

        df_nodes = df_nodes.merge(
            primera_nodo.rename("primera_fecha_nodo"),
            left_on="numero",
            right_index=True,
            how="left",
        )
        df_nodes = df_nodes.merge(
            ultima_nodo.rename("ultima_fecha_nodo"),
            left_on="numero",
            right_index=True,
            how="left",
        )

    # Limitar número de nodos para el grafo
    if len(df_nodes) > max_nodos:
        nodos_seleccionados = df_nodes.head(max_nodos)["numero"].tolist()
        df_nodes = df_nodes[df_nodes["numero"].isin(nodos_seleccionados)]
        df_edges = df_edges[
            df_edges["n1"].isin(nodos_seleccionados)
            & df_edges["n2"].isin(nodos_seleccionados)
        ]

    # -------------------------
    # 6) Métricas rápidas
    # -------------------------
    render_section("Métricas rápidas", "Lectura ejecutiva de centralidad y volumen antes de revisar el grafo.", "04")
    kpi_row([
        {"label": "Nodos", "value": f"{len(df_nodes):,}", "help": "Números en la red"},
        {"label": "Vínculos", "value": f"{len(df_edges):,}", "help": "Relaciones dirigidas"},
        {"label": "Eventos", "value": f"{int(df_edges['conteo'].sum()):,}", "help": "Eventos agregados"},
    ], columns=3)

    col_m1, col_m2 = st.columns(2)

    with col_m1:
        render_step_header("A", "Top 10 por grado", "Números con más contactos distintos.")
        tabla_grado = (
            df_nodes.sort_values("grado", ascending=False)[
                ["numero", "grado", "total_eventos"]
            ]
            .head(10)
            .reset_index(drop=True)
        )
        st.dataframe(tabla_grado, use_container_width=True)

    with col_m2:
        render_step_header("B", "Top 10 por volumen", "Números con mayor actividad agregada.")
        tabla_volumen = (
            df_nodes.sort_values("total_eventos", ascending=False)[
                ["numero", "total_eventos", "grado"]
            ]
            .head(10)
            .reset_index(drop=True)
        )
        st.dataframe(tabla_volumen, use_container_width=True)

    # -------------------------
    # 7) Grafo interactivo
    # -------------------------
    render_section("Grafo interactivo", "Visual principal de relaciones; las tablas quedan como evidencia auxiliar.", "05")

    opciones_nums = df_nodes["numero"].astype(str).tolist()
    if not opciones_nums:
        st.warning("No hay nodos para graficar.")
        return

    # Número objetivo por defecto: el de mayor volumen
    default_obj = str(
        df_nodes.sort_values("total_eventos", ascending=False)["numero"].iloc[0]
    )
    try:
        default_index = opciones_nums.index(default_obj)
    except ValueError:
        default_index = 0

    numero_objetivo = st.selectbox(
        "Número objetivo principal (abonado investigado)",
        options=opciones_nums,
        index=default_index,
    )

    # ---- etiquetas de modos de grafo ----
    GRAFO_CIRC_FIS = "Circular alrededor del número objetivo (solo contactos directos, con física)"
    GRAFO_CIRC_FIJO = "Circular fijo alrededor del número objetivo (solo contactos directos, sin física)"
    GRAFO_FUERZAS = "Layout de fuerzas (libre, toda la red)"

    tipo_grafo = st.selectbox(
        "Tipo de grafo",
        [
            GRAFO_CIRC_FIS,
            GRAFO_CIRC_FIJO,
            GRAFO_FUERZAS,
        ],
        index=0,
        help=(
            "Circular (con física): estrella alrededor del objetivo, contactos directos.\n"
            "Circular fijo: misma estrella pero sin física (flechas cortas y posiciones fijas).\n"
            "Fuerzas: toda la red con física (no solo contactos directos)."
        ),
    )

    # Rango temporal global
    if col_fecha and df[col_fecha].notna().any():
        dt_min = df[col_fecha].min()
        dt_max = df[col_fecha].max()
        st.markdown(
            f"**Rango temporal analizado:** {_fmt_dt(dt_min)} → {_fmt_dt(dt_max)}"
        )

    # Leyenda de colores
    st.markdown(
        """
        **Leyenda de colores de flechas (tipo de evento por vínculo):**  
        <span style='color:#00AA00;font-weight:bold;'>Verde</span>: llamadas entrantes  
        <span style='color:#DD0000;font-weight:bold;'>Rojo</span>: llamadas salientes  
        <span style='color:#800080;font-weight:bold;'>Morado</span>: SMS / mensajes  
        <span style='color:#808080;font-weight:bold;'>Gris</span>: otros o sin tipo definido  
        """,
        unsafe_allow_html=True,
    )

    # --- Subconjunto para el grafo según modo ---
    df_nodes_g = df_nodes.copy()
    df_edges_g = df_edges.copy()

    if tipo_grafo in (GRAFO_CIRC_FIS, GRAFO_CIRC_FIJO):
        # Solo vínculos donde participe el número objetivo → grafo tipo estrella
        edges_focus = df_edges[
            (df_edges["n1"].astype(str) == numero_objetivo)
            | (df_edges["n2"].astype(str) == numero_objetivo)
        ].copy()
        if not edges_focus.empty:
            df_edges_g = edges_focus
            nodos_set = (
                set(edges_focus["n1"].astype(str))
                | set(edges_focus["n2"].astype(str))
            )
            nodos_set.add(numero_objetivo)
            df_nodes_g = df_nodes[df_nodes["numero"].astype(str).isin(nodos_set)].copy()

    # --- Construcción del grafo PyVis ---
    net = Network(
        height="650px",
        width="100%",
        bgcolor="#ffffff",
        font_color="#000000",
        directed=True,
    )

    # Física / layout según modo
    if tipo_grafo == GRAFO_FUERZAS:
        net.barnes_hut()
    elif tipo_grafo == GRAFO_CIRC_FIS:
        # física suave con posiciones iniciales
        net.barnes_hut()
    elif tipo_grafo == GRAFO_CIRC_FIJO:
        # sin física, solo usamos posiciones fijas
        net.set_options(json.dumps({"physics": {"enabled": False}}))

    # Posiciones iniciales para el modo circular estrella
    posiciones: dict[str, tuple[float, float]] = {}
    if tipo_grafo in (GRAFO_CIRC_FIS, GRAFO_CIRC_FIJO):
        posiciones[numero_objetivo] = (0.0, 0.0)
        nums_layout = df_nodes_g["numero"].astype(str).tolist()
        otros = [n for n in nums_layout if n != numero_objetivo]
        r = 400.0
        for i, n in enumerate(otros):
            angle = 2 * math.pi * i / max(len(otros), 1)
            x = r * math.cos(angle)
            y = r * math.sin(angle)
            posiciones[n] = (x, y)

    # Tamaño de nodos (escala sobre lo que se grafica)
    min_ev = df_nodes_g["total_eventos"].min()
    max_ev = df_nodes_g["total_eventos"].max()
    if min_ev == max_ev:
        df_nodes_g["size"] = 25.0
    else:
        df_nodes_g["size"] = 10.0 + (df_nodes_g["total_eventos"] - min_ev) * 40.0 / (
            max_ev - min_ev
        )

    # Añadir nodos
    for _, row in df_nodes_g.iterrows():
        num = str(row["numero"])
        size = float(row["size"])
        grado = int(row["grado"])
        total_ev = int(row["total_eventos"])

        title_parts = [
            f"Número: {num}",
            f"Total de eventos: {total_ev}",
            f"Grado (contactos distintos): {grado}",
        ]
        if "primera_fecha_nodo" in row and not pd.isna(row["primera_fecha_nodo"]):
            title_parts.append(f"Primer evento: {_fmt_dt(row['primera_fecha_nodo'])}")
        if "ultima_fecha_nodo" in row and not pd.isna(row["ultima_fecha_nodo"]):
            title_parts.append(f"Último evento: {_fmt_dt(row['ultima_fecha_nodo'])}")

        if num == numero_objetivo:
            size = max(size * 1.3, size + 5.0)
            node_color = "#FFD700"
            title_parts.append("<b>Rol: Número objetivo principal</b>")
        else:
            node_color = "#97C2FC"

        node_kwargs = {
            "label": num,
            "title": "<br>".join(title_parts),
            "value": float(total_ev),
            "size": size,
            "color": node_color,
        }

        if tipo_grafo in (GRAFO_CIRC_FIS, GRAFO_CIRC_FIJO) and num in posiciones:
            x, y = posiciones[num]
            node_kwargs["x"] = float(x)
            node_kwargs["y"] = float(y)

        net.add_node(num, **node_kwargs)

    # Flechas: grosor proporcional a la actividad
    edge_colors_map = {
        "ENTRANTE": "#00AA00",
        "SALIENTE": "#DD0000",
        "SMS": "#800080",
        "OTRO": "#808080",
    }

    all_counts = []
    for c in ["ENTRANTE", "SALIENTE", "SMS", "OTRO"]:
        if c in df_edges_g.columns:
            all_counts.extend(df_edges_g[c][df_edges_g[c] > 0].tolist())

    if all_counts:
        min_cnt = min(all_counts)
        max_cnt = max(all_counts)
    else:
        min_cnt = max_cnt = None

    for _, row in df_edges_g.iterrows():
        a = str(row["n1"])
        b = str(row["n2"])
        total_pair = int(row["conteo"])

        for tipo, col_name, label in [
            ("ENTRANTE", "ENTRANTE", "Llamadas entrantes"),
            ("SALIENTE", "SALIENTE", "Llamadas salientes"),
            ("SMS", "SMS", "SMS / mensajes"),
            ("OTRO", "OTRO", "Otros / sin tipo definido"),
        ]:
            cnt = int(row.get(col_name, 0) or 0)
            if cnt <= 0:
                continue

            if min_cnt is None or min_cnt == max_cnt:
                width = 2.0
            else:
                width = 1.0 + (cnt - min_cnt) * 9.0 / (max_cnt - min_cnt)

            color = edge_colors_map.get(tipo, "#808080")

            tooltip_lines = [
                f"{a} → {b}",
                f"Eventos ({label}): {cnt}",
                f"Eventos totales entre ambos números: {total_pair}",
            ]

            if "duracion_total_seg" in row and not pd.isna(row["duracion_total_seg"]):
                tooltip_lines.append(
                    f"Duración total (todos los tipos): {int(row['duracion_total_seg'])} s"
                )

            if "primera_fecha" in row and not pd.isna(row["primera_fecha"]):
                tooltip_lines.append(
                    f"Primer evento: {_fmt_dt(row['primera_fecha'])}"
                )
            if "ultima_fecha" in row and not pd.isna(row["ultima_fecha"]):
                tooltip_lines.append(
                    f"Último evento: {_fmt_dt(row['ultima_fecha'])}"
                )

            net.add_edge(
                a,
                b,
                value=float(cnt),
                title="<br>".join(tooltip_lines),
                width=width,
                color=color,
            )

    _plot_pyvis(net)

    # -------------------------
    # 8) Descargas
    # -------------------------
    render_section("Tablas de soporte y descargas", "Exportables auxiliares para respaldar el análisis visual.", "06")

    col_d1, col_d2, col_d3 = st.columns(3)

    with col_d1:
        b1 = _to_excel_bytes(df_nodes[["numero", "grado", "total_eventos"]])
        st.download_button(
            "📥 Descargar nodos (números) en Excel",
            data=b1,
            file_name="link_analysis_nodos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col_d2:
        b2 = _to_excel_bytes(df_edges)
        st.download_button(
            "📥 Descargar vínculos dirigidos en Excel",
            data=b2,
            file_name="link_analysis_vinculos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col_d3:
        png_bytes = _build_png_graph(df_nodes, df_edges, numero_objetivo)
        if png_bytes is not None:
            st.download_button(
                "📥 Descargar imagen PNG del grafo",
                data=png_bytes,
                file_name="link_analysis_grafo.png",
                mime="image/png",
            )
        else:
            st.info(
                "Para exportar el grafo como imagen PNG instala `networkx` y `matplotlib` "
                "y agrégalas a tu `requirements.txt`."
            )


if __name__ == "__main__":
    main()
