# -*- coding: utf-8 -*-
"""
Sentinel Mapper KMZ Pro — Interfaz mínima v1.9

Visible:
- Subir Excel/CSV.
- Filtro por tipo: DATOS, LLAMADAS, SMS.
- Color de ruta.
- Generar KMZ.

Oculto/default:
- Columnas detectadas automáticamente.
- Modo pericial.
- Popup completo.
- Radio cobertura 800 m.
- Radio azimuth 800 m.
- Apertura 30°.
- Antena y brújula automáticas desde /assets.
- Ruta vial azimuth → azimuth para búsqueda de cámaras.
"""

from __future__ import annotations

from pathlib import Path
import re

import pandas as pd
import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")
from ui.styles import apply_theme, kpi_row, page_header, section_title
from ui.components import render_card, render_step_header

# =========================
#   GUARDIAN / SIDEBAR
# =========================
try:
    from guardian import login_guard
except Exception:
    login_guard = None

try:
    from suite_nav import render_suite_sidebar
except Exception:
    render_suite_sidebar = None


# =========================
#   MOTOR KMZ PRO
# =========================
try:
    from core.kmz_pro_builder import (
        KMZProOptions,
        build_kmz_pro,
        detect_mapping,
        prepare_dataframe,
    )
except Exception as e:
    st.error("No se pudieron importar los módulos de Sentinel Mapper KMZ Pro.")
    st.exception(e)
    st.stop()


# =========================
#   ASSETS
# =========================
ROOT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT_DIR / "assets"

ANTENNA_ASSET_CANDIDATES = [
    "antena_oficial.png",
    "antena_oficial.jpg",
    "antena.png",
    "antenna.png",
    "icono_antena.png",
]

COMPASS_ASSET_CANDIDATES = [
    "BRUJULA AZIMUTH SIN RELLENO.png",
    "brujula.png",
    "brujula_oficial.png",
    "compass.png",
    "norte.png",
]

ROUTE_COLOR_MAP = {
    "Verde operativo": "ff00ff00",
    "Azul": "ffff6600",
    "Cian": "ffffff00",
    "Amarillo": "ff00ffff",
    "Naranja": "ff008cff",
    "Rojo": "ff0000ff",
    "Morado": "ffff00aa",
    "Blanco": "ffffffff",
}


def _apply_guardian():
    if login_guard is not None:
        login_guard("Sentinel Mapper KMZ Pro")
    if render_suite_sidebar is not None:
        render_suite_sidebar()


def _find_asset(candidates):
    for name in candidates:
        path = ASSETS_DIR / name
        if path.exists() and path.is_file():
            return path
    return None


def _safe_ext(filename: str, default: str = ".png") -> str:
    ext = Path(filename or "").suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return ext
    return default


def _read_table(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def _build_assets_auto():
    """
    Usa siempre los archivos de /assets si existen.
    No muestra controles ni solicita carga manual.
    """
    kmz_assets = {}
    antenna_href = None
    compass_href = None

    ant_path = _find_asset(ANTENNA_ASSET_CANDIDATES)
    if ant_path:
        internal = f"files/antenna_icon{_safe_ext(ant_path.name)}"
        kmz_assets[internal] = ant_path.read_bytes()
        antenna_href = internal

    compass_path = _find_asset(COMPASS_ASSET_CANDIDATES)
    if compass_path:
        internal = f"files/compass_icon{_safe_ext(compass_path.name)}"
        kmz_assets[internal] = compass_path.read_bytes()
        compass_href = internal

    return antenna_href, compass_href, kmz_assets


def _norm_txt(value) -> str:
    txt = str(value or "").strip().upper()
    repl = {
        "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U",
        "Ñ": "N",
    }
    for a, b in repl.items():
        txt = txt.replace(a, b)
    txt = re.sub(r"\s+", " ", txt)
    return txt


def _classify_event_type(value) -> str:
    txt = _norm_txt(value)

    if any(x in txt for x in ["VOZ", "LLAMADA", "CALL"]):
        return "LLAMADAS"

    if any(x in txt for x in ["SMS", "MENSAJE", "MESSAGE"]):
        return "SMS"

    if any(x in txt for x in ["DATO", "DATOS", "DATA", "GPRS", "INTERNET", "IMS"]):
        return "DATOS"

    return "OTROS"


def _filter_by_type(df: pd.DataFrame, mapping: dict, selected_categories: list[str]) -> pd.DataFrame:
    tipo_col = mapping.get("tipo")
    if not tipo_col or tipo_col not in df.columns:
        return df.copy()

    if not selected_categories:
        return df.iloc[0:0].copy()

    work = df.copy()
    work["__categoria_evento_tmp"] = work[tipo_col].apply(_classify_event_type)
    work = work[work["__categoria_evento_tmp"].isin(selected_categories)].copy()
    work = work.drop(columns=["__categoria_evento_tmp"], errors="ignore")
    return work


def _build_default_options(antenna_href, compass_href, route_color: str) -> KMZProOptions:
    """
    Valores default aprobados por el flujo actual.
    """
    return KMZProOptions(
        case_title="Sentinel Mapper KMZ Pro",
        modo="pericial",
        popup_detail="completo",

        coverage_radius_m=800,
        azimuth_radius_m=800,
        azimuth_aperture_deg=30,

        show_antennas=True,
        show_coverage=True,
        show_azimuth=True,
        show_compass=True,
        show_routes_by_day=True,
        show_relevant_events=False,
        group_events_by_day=True,

        route_width=3,
        antenna_icon_href=antenna_href,
        compass_icon_href=compass_href,
        compass_radius_m=300,
        antenna_icon_color="ffffffff",

        # Modo principal fijo.
        route_mode="ruta_vial_azimuth",
        route_azimuth_factor=0.65,

        # Azimuth chain / road route.
        show_azimuth_chain_points=False,
        link_last_azimuth_to_last_antenna=True,
        consolidate_same_azimuth_sector=True,
        azimuth_chain_max_points=300,

        show_azimuth_road_corridor=True,
        azimuth_road_buffer_m=100,
        show_azimuth_road_camera_points=False,
        azimuth_road_camera_interval_m=200,
        show_azimuth_road_direct_reference=False,
        max_azimuth_road_segments=30,
        draw_full_azimuth_road_sequence=True,
        camera_search_margin_min=15,
        azimuth_road_route_color=route_color,

        # Solo negocios/empresas reales OSM dentro del corredor.
        show_osm_business_camera_points=True,
        osm_business_max_per_segment=25,
        osm_business_timeout_s=18,

        # OSRM.
        osrm_profile="driving",
        osrm_timeout_s=8,

        # Compatibilidad con modos previos.
        show_operational_route_corridor=True,
        operational_route_buffer_m=100,
        show_camera_search_points=True,
        camera_search_interval_m=200,
        show_direct_reference_line=True,
        max_operational_segments=30,
    )


def render():
    _apply_guardian()
    apply_theme()

    page_header(
        "Sentinel Mapper KMZ Pro",
        "Genera productos KMZ profesionales con antenas, eventos, cobertura referencial, azimuth, rutas y popups periciales.",
        eyebrow="GEOANÁLISIS KMZ",
        badges=["KMZ/KML", "Azimuth", "Ruta operativa"],
    )
    with render_card():
        render_step_header("01", "Archivo", "Carga el Excel limpio de Go Suite Mapper o un CSV compatible.")
        uploaded = st.file_uploader(
            "Archivo fuente",
            type=["xlsx", "xls", "csv"],
        )

    if not uploaded:
        return

    try:
        df = _read_table(uploaded)
    except Exception as e:
        st.error("No pude leer el archivo.")
        st.exception(e)
        return

    if df.empty:
        st.warning("El archivo no contiene registros.")
        return

    mapping = detect_mapping(df)

    missing = [k for k in ["latitud", "longitud"] if not mapping.get(k)]
    if missing:
        st.error(
            "No pude detectar columnas mínimas requeridas: "
            + ", ".join(missing)
            + ". Verifica que el archivo tenga Latitud y Longitud."
        )
        return

    tipo_col = mapping.get("tipo")
    default_categories = ["DATOS", "LLAMADAS", "SMS"]

    with render_card():
        render_step_header("02", "Columnas detectadas", "Revisión visual del mapeo automático usado por el motor KMZ.")
        mapping_rows = [
            {"Campo": key, "Columna detectada": value or "—"}
            for key, value in mapping.items()
            if key in {"telefono", "tipo", "numero_a", "numero_b", "fecha", "hora", "datetime", "latitud", "longitud", "azimuth", "direccion", "plus_code"}
        ]
        st.dataframe(pd.DataFrame(mapping_rows), use_container_width=True, height=220)

    with render_card():
        render_step_header("03", "Filtros", "Selecciona las categorías de evento que entrarán al producto geográfico.")
        selected_categories = st.multiselect(
            "Tipo de eventos a incluir",
            options=default_categories,
            default=default_categories,
        )

    filtered = _filter_by_type(df, mapping, selected_categories)

    with render_card():
        render_step_header("04", "Métricas", "Conteo operativo antes de construir el KMZ.")
        try:
            prepared_preview = prepare_dataframe(filtered, mapping)
            mapeables = int(prepared_preview["__is_mappable"].sum())
            kpi_row([
                {"label": "Registros seleccionados", "value": f"{len(filtered):,}", "help": "Después del filtro de tipo"},
                {"label": "Eventos mapeables", "value": f"{mapeables:,}", "help": "Con latitud/longitud válidas"},
            ], columns=2)
        except Exception:
            st.caption(f"Registros seleccionados: {len(filtered):,}")

    with render_card():
        render_step_header("05", "Configuración KMZ", "Ajustes visuales del producto sin modificar el motor geográfico.")
        route_color_label = st.selectbox(
            "Color de la ruta",
            list(ROUTE_COLOR_MAP.keys()),
            index=0,
        )

    route_color = ROUTE_COLOR_MAP.get(route_color_label, "ff00ff00")
    antenna_href, compass_href, kmz_assets = _build_assets_auto()
    options = _build_default_options(
        antenna_href=antenna_href,
        compass_href=compass_href,
        route_color=route_color,
    )

    with render_card():
        render_step_header("06", "Generar producto", "Construye y descarga el KMZ Pro con los parámetros seleccionados.")
        generate = st.button("🚀 Generar KMZ Pro", type="primary")

    if generate:
        if filtered.empty:
            st.warning("No hay registros para generar con el filtro seleccionado.")
            return

        try:
            with st.spinner("Construyendo KMZ Pro..."):
                kmz_bytes, filename, used_mapping, prepared = build_kmz_pro(
                    filtered,
                    options=options,
                    mapping=mapping,
                    kmz_assets=kmz_assets,
                )

            mapeables = int(prepared["__is_mappable"].sum()) if "__is_mappable" in prepared.columns else 0

            st.success("KMZ Pro generado correctamente.")
            st.write(f"**Registros procesados:** {len(prepared):,}")
            st.write(f"**Eventos mapeables:** {mapeables:,}")

            st.download_button(
                "⬇️ Descargar KMZ Pro",
                data=kmz_bytes,
                file_name=filename,
                mime="application/vnd.google-earth.kmz",
                use_container_width=True,
            )

        except Exception as e:
            st.error("No se pudo generar el KMZ Pro.")
            st.exception(e)


if __name__ == "__main__":
    render()
