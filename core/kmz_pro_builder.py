# -*- coding: utf-8 -*-
"""
Motor de construcción KMZ para Sentinel Mapper KMZ Pro.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import tempfile
import zipfile
from typing import Optional

import pandas as pd

try:
    import simplekml
except Exception:  # pragma: no cover
    simplekml = None

from .kmz_pro_analysis import antenna_groups, build_summary, relevant_events
from .kmz_pro_popups import antenna_popup, event_popup, relevant_popup, summary_popup
from .kmz_pro_styles import (
    COLOR_BLACK,
    COLOR_BLUE,
    COLOR_CYAN,
    COLOR_GRAY,
    COLOR_LIME,
    COLOR_ORANGE,
    COLOR_PURPLE,
    COLOR_WHITE,
    ICON_URLS,
    POLY_BLUE_TRANSPARENT,
    POLY_CYAN_TRANSPARENT,
    POLY_GRAY_TRANSPARENT,
    POLY_LIME_TRANSPARENT,
    apply_icon_style,
    apply_line_style,
    apply_polygon_style,
    get_event_style,
)
from .kmz_pro_routing import (
    corridor_polygon,
    format_distance,
    format_duration,
    osrm_route,
    overpass_business_pois_near_route,
    polyline_distance_m,
    sample_points_along_line,
)

from .kmz_pro_utils import (
    circle_coords,
    first_existing_column,
    line_coords_from_df,
    normalize_datetime,
    normalize_event_type,
    safe_filename,
    safe_text,
    sector_coords,
    to_float,
    valid_lat_lon,
)


@dataclass
class KMZProOptions:
    case_title: str = "Sentinel Mapper KMZ Pro"
    modo: str = "operativo"  # operativo | pericial
    popup_detail: str = "completo"  # basico | medio | completo
    coverage_radius_m: int = 800
    azimuth_radius_m: int = 800
    azimuth_aperture_deg: int = 30
    show_antennas: bool = True
    show_coverage: bool = True
    show_azimuth: bool = True
    show_compass: bool = False
    show_routes_by_day: bool = True
    show_relevant_events: bool = True
    group_events_by_day: bool = True
    route_width: int = 3

    # Iconografía personalizada.
    # Si se usan archivos embebidos dentro del KMZ, estos href deben apuntar a rutas internas:
    # ejemplo: files/antenna_icon.png, files/compass_icon.png
    antenna_icon_href: Optional[str] = None
    compass_icon_href: Optional[str] = None
    compass_radius_m: int = 300

    # Preserva el color original del PNG cuando se usa "ffffffff".
    # KML usa formato aabbggrr.
    antenna_icon_color: str = "ffffffff"

    # "antena": conecta las coordenadas de antena/celda.
    # "centro_azimuth": conecta un punto estimado dentro del sector azimuth.
    route_mode: str = "centro_azimuth"
    route_azimuth_factor: float = 0.65

    # Ruta probable de búsqueda operativa.
    # route_mode="ruta_operativa_osrm" calcula ruta por calles entre puntos estimados por azimuth.
    show_operational_route_corridor: bool = True
    operational_route_buffer_m: int = 100
    show_camera_search_points: bool = True
    camera_search_interval_m: int = 200
    show_direct_reference_line: bool = True
    osrm_profile: str = "driving"
    osrm_timeout_s: int = 8
    max_operational_segments: int = 30

    # Enlace cronológico azimuth → azimuth.
    show_azimuth_chain_points: bool = True
    link_last_azimuth_to_last_antenna: bool = True
    consolidate_same_azimuth_sector: bool = True
    azimuth_chain_max_points: int = 300

    # Ruta vial realista entre puntos proyectados del azimuth.
    # Similar a una ruta por calles tipo Dijkstra/OSRM entre zonas estimadas.
    show_azimuth_road_corridor: bool = True
    azimuth_road_buffer_m: int = 100
    show_azimuth_road_camera_points: bool = True
    azimuth_road_camera_interval_m: int = 200
    show_azimuth_road_direct_reference: bool = True
    max_azimuth_road_segments: int = 30
    draw_full_azimuth_road_sequence: bool = True

    # Ventana sugerida para búsqueda de video/cámaras.
    # Se calcula entre la hora del evento origen y destino, con margen operativo.
    camera_search_margin_min: int = 15

    # Color de ruta vial azimuth → azimuth. Formato KML aabbggrr.
    azimuth_road_route_color: str = "ff00ff00"

    # OpenStreetMap / Overpass: negocios reales dentro del corredor.
    show_osm_business_camera_points: bool = True
    osm_business_max_per_segment: int = 25
    osm_business_timeout_s: int = 18


DEFAULT_COLUMN_CANDIDATES = {
    "telefono": ["Teléfono", "Telefono", "Teléfono Investigado", "Telefono Investigado", "MSISDN", "Numero Investigado"],
    "tipo": ["Tipo", "T_REG", "Servicio", "SERV", "Tipo Evento", "Evento"],
    "numero_a": ["Número A", "Numero A", "Num A", "Origen", "A"],
    "numero_b": ["Número B", "Numero B", "Num B", "Destino", "Contacto", "B", "APN"],
    "fecha": ["Fecha", "Date", "F_INI", "Fecha Inicio"],
    "hora": ["Hora", "Time", "H_INI", "Hora Inicio"],
    "datetime": ["Datetime", "FechaHora", "Fecha Hora", "Fecha_Hora", "Timestamp", "DateTime"],
    "duracion": ["Duración (seg)", "Duracion (seg)", "Duración", "Duracion", "Duration", "Segundos"],
    "imei": ["IMEI", "Imei", "Terminal", "Equipo"],
    "latitud": ["Latitud", "Latitude", "LAT", "Lat"],
    "longitud": ["Longitud", "Longitude", "LON", "LONG", "Lng", "Lon"],
    "azimuth": ["Azimuth", "Azimut", "AZIMUTH", "AZ"],
    "direccion": ["Dirección", "Direccion", "PLUS_CODE_NOMBRE", "Domicilio", "Ubicación", "Ubicacion"],
    "plus_code": ["PLUS_CODE", "Plus Code", "OLC"],
}


def detect_mapping(df: pd.DataFrame) -> dict:
    return {key: first_existing_column(df, candidates) for key, candidates in DEFAULT_COLUMN_CANDIDATES.items()}


def prepare_dataframe(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    work = df.copy()

    tipo_col = mapping.get("tipo")
    if tipo_col and tipo_col in work.columns:
        work["__tipo"] = work[tipo_col].apply(normalize_event_type)
    else:
        work["__tipo"] = "SIN TIPO"

    work = normalize_datetime(work, mapping)

    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    if lat_col and lon_col:
        work["__is_mappable"] = work.apply(
            lambda r: valid_lat_lon(to_float(r.get(lat_col)), to_float(r.get(lon_col))),
            axis=1
        )
    else:
        work["__is_mappable"] = False

    if "__datetime" in work.columns:
        work = work.sort_values(["__datetime"], na_position="last").reset_index(drop=True)

    return work


def _new_folder(parent, name: str):
    return parent.newfolder(name=name)


def _add_summary(kml, df: pd.DataFrame, mapping: dict, options: KMZProOptions):
    folder = kml.newfolder(name="00_Resumen del caso")
    summary = build_summary(df, mapping)

    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    lat = lon = None
    if lat_col and lon_col:
        valid = df[df["__is_mappable"]] if "__is_mappable" in df.columns else df
        if not valid.empty:
            lat = to_float(valid.iloc[0].get(lat_col))
            lon = to_float(valid.iloc[0].get(lon_col))

    if not valid_lat_lon(lat, lon):
        return

    p = folder.newpoint(name="Resumen del caso", coords=[(float(lon), float(lat))])
    p.description = summary_popup(summary, modo=options.modo)
    apply_icon_style(p, COLOR_BLUE, ICON_URLS["info"], scale=1.2, label_scale=0.9)


def _add_antenna_layers(kml, df: pd.DataFrame, mapping: dict, options: KMZProOptions):
    if not options.show_antennas:
        return

    groups = antenna_groups(df, mapping)
    if groups.empty:
        return

    root = kml.newfolder(name="01_Antenas utilizadas")
    ant_folder = _new_folder(root, "Antenas")
    cov_folder = _new_folder(root, f"Cobertura referencial {options.coverage_radius_m}m") if options.show_coverage else None
    azi_folder = _new_folder(root, "Azimuth sectorial") if options.show_azimuth else None
    compass_folder = _new_folder(root, "Brújula / Norte") if options.show_compass else None

    for i, row in groups.iterrows():
        lat = float(row["lat"])
        lon = float(row["lon"])
        az = row.get("azimuth")

        name = f"Antena {i+1:03d} | Eventos: {int(row['total'])}"
        group_info = row.to_dict()
        group_info["name"] = name

        p = ant_folder.newpoint(name=name, coords=[(lon, lat)])
        p.description = antenna_popup(group_info, modo=options.modo)
        antenna_icon = options.antenna_icon_href or ICON_URLS["antenna"]
        antenna_color = getattr(options, "antenna_icon_color", COLOR_WHITE) or COLOR_WHITE
        apply_icon_style(p, antenna_color, antenna_icon, scale=1.05, label_scale=0.75)

        if cov_folder is not None:
            poly = cov_folder.newpolygon(
                name=f"Cobertura {i+1:03d}",
                outerboundaryis=circle_coords(lat, lon, options.coverage_radius_m, steps=72)
            )
            poly.description = antenna_popup(group_info, modo=options.modo)
            apply_polygon_style(poly, COLOR_GRAY, POLY_GRAY_TRANSPARENT, line_width=1)

        if azi_folder is not None and az is not None and not pd.isna(az) and float(az) >= 0:
            poly = azi_folder.newpolygon(
                name=f"Azimuth {int(float(az))}° | Antena {i+1:03d}",
                outerboundaryis=sector_coords(
                    lat,
                    lon,
                    float(az),
                    options.azimuth_radius_m,
                    aperture_deg=options.azimuth_aperture_deg,
                    steps=28
                )
            )
            poly.description = antenna_popup(group_info, modo=options.modo)
            apply_polygon_style(poly, COLOR_BLUE, POLY_BLUE_TRANSPARENT, line_width=2)

        if compass_folder is not None:
            from .kmz_pro_utils import bearing_destination

            if options.compass_icon_href:
                # Brújula como GroundOverlay embebido o referenciado.
                radius = float(options.compass_radius_m or min(300, options.coverage_radius_m * 0.40))
                north_lat, _ = bearing_destination(lat, lon, 0, radius)
                south_lat, _ = bearing_destination(lat, lon, 180, radius)
                _, east_lon = bearing_destination(lat, lon, 90, radius)
                _, west_lon = bearing_destination(lat, lon, 270, radius)

                overlay = compass_folder.newgroundoverlay(name=f"Brújula | Antena {i+1:03d}")
                overlay.icon.href = options.compass_icon_href
                overlay.latlonbox.north = north_lat
                overlay.latlonbox.south = south_lat
                overlay.latlonbox.east = east_lon
                overlay.latlonbox.west = west_lon
                overlay.latlonbox.rotation = 0
                overlay.description = antenna_popup(group_info, modo=options.modo)
            else:
                # Fallback: Norte y ejes cardinales como líneas simples.
                for label, bearing, color, width in [
                    ("N", 0, COLOR_BLACK, 3),
                    ("E", 90, COLOR_GRAY, 1),
                    ("S", 180, COLOR_GRAY, 1),
                    ("W", 270, COLOR_GRAY, 1),
                ]:
                    dlat, dlon = bearing_destination(lat, lon, bearing, min(250, options.coverage_radius_m * 0.35))
                    line = compass_folder.newlinestring(
                        name=f"{label} | Antena {i+1:03d}",
                        coords=[(lon, lat), (dlon, dlat)]
                    )
                    apply_line_style(line, color=color, width=width)


def _event_point_name(idx: int, row: dict, mapping: dict) -> str:
    tipo = safe_text(row.get("__tipo", "Evento"))
    fecha = safe_text(row.get("__date", ""))
    hora = safe_text(row.get("__time", ""))
    nb_col = mapping.get("numero_b")
    contacto = safe_text(row.get(nb_col, ""), default="")
    suffix = f" | {contacto}" if contacto else ""
    return f"{idx:04d} | {fecha} {hora} | {tipo}{suffix}"


def _add_events(kml, df: pd.DataFrame, mapping: dict, options: KMZProOptions):
    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    if not lat_col or not lon_col:
        return

    root = kml.newfolder(name="02_Eventos de comunicación")
    mappable = df[df["__is_mappable"]].copy() if "__is_mappable" in df.columns else df.copy()
    if mappable.empty:
        return

    if options.group_events_by_day:
        for day, gday in mappable.groupby("__date", dropna=False):
            day_folder = _new_folder(root, str(day))
            for tipo, gtipo in gday.groupby("__tipo", dropna=False):
                type_folder = _new_folder(day_folder, str(tipo))
                _add_event_points_to_folder(type_folder, gtipo, mapping, options)
    else:
        for tipo, gtipo in mappable.groupby("__tipo", dropna=False):
            type_folder = _new_folder(root, str(tipo))
            _add_event_points_to_folder(type_folder, gtipo, mapping, options)


def _add_event_points_to_folder(folder, df: pd.DataFrame, mapping: dict, options: KMZProOptions):
    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")

    for idx, (_, row) in enumerate(df.iterrows(), start=1):
        lat = to_float(row.get(lat_col))
        lon = to_float(row.get(lon_col))
        if not valid_lat_lon(lat, lon):
            continue

        tipo = row.get("__tipo", "SIN TIPO")
        sty = get_event_style(tipo)

        p = folder.newpoint(
            name=_event_point_name(idx, row.to_dict(), mapping),
            coords=[(float(lon), float(lat))]
        )
        p.description = event_popup(row.to_dict(), mapping, modo=options.modo, detail=options.popup_detail)
        apply_icon_style(p, sty["color"], sty["icon"], scale=0.8, label_scale=0.0)



def _fmt_event_dt(value) -> str:
    try:
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            return "S/D"
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "S/D"


def _fmt_event_time(value) -> str:
    try:
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            return "S/D"
        return dt.strftime("%H:%M:%S")
    except Exception:
        return "S/D"


def _camera_search_window(row_a: dict, row_b: dict, margin_min: int = 15) -> dict:
    """
    Calcula ventana sugerida de búsqueda de video:
    - Rango base: evento origen → evento destino.
    - Rango con margen: origen - margen → destino + margen.
    """
    try:
        da = pd.to_datetime(row_a.get("__datetime"), errors="coerce")
        db = pd.to_datetime(row_b.get("__datetime"), errors="coerce")
        if pd.isna(da) or pd.isna(db):
            return {
                "evento_origen": "S/D",
                "evento_destino": "S/D",
                "rango_base": "S/D",
                "rango_margen": "S/D",
                "margen": f"±{int(margin_min)} min",
            }

        start = min(da, db)
        end = max(da, db)
        margin = pd.Timedelta(minutes=int(margin_min or 0))
        start_m = start - margin
        end_m = end + margin

        same_day = start.date() == end.date()
        same_day_m = start_m.date() == end_m.date()

        if same_day:
            rango_base = f"{start.strftime('%Y-%m-%d')} | {start.strftime('%H:%M:%S')} a {end.strftime('%H:%M:%S')}"
        else:
            rango_base = f"{start.strftime('%Y-%m-%d %H:%M:%S')} a {end.strftime('%Y-%m-%d %H:%M:%S')}"

        if same_day_m:
            rango_margen = f"{start_m.strftime('%Y-%m-%d')} | {start_m.strftime('%H:%M:%S')} a {end_m.strftime('%H:%M:%S')}"
        else:
            rango_margen = f"{start_m.strftime('%Y-%m-%d %H:%M:%S')} a {end_m.strftime('%Y-%m-%d %H:%M:%S')}"

        return {
            "evento_origen": da.strftime("%Y-%m-%d %H:%M:%S"),
            "evento_destino": db.strftime("%Y-%m-%d %H:%M:%S"),
            "rango_base": rango_base,
            "rango_margen": rango_margen,
            "margen": f"±{int(margin_min)} min",
        }
    except Exception:
        return {
            "evento_origen": "S/D",
            "evento_destino": "S/D",
            "rango_base": "S/D",
            "rango_margen": "S/D",
            "margen": f"±{int(margin_min)} min",
        }

def _time_diff_label(a, b) -> str:
    try:
        da = pd.to_datetime(a, errors="coerce")
        db = pd.to_datetime(b, errors="coerce")
        if pd.isna(da) or pd.isna(db):
            return "S/D"
        seconds = abs((db - da).total_seconds())
        if seconds >= 3600:
            return f"{seconds/3600:.1f} h"
        return f"{seconds/60:.0f} min"
    except Exception:
        return "S/D"


def _operational_route_popup(
    segment_name: str,
    row_a: dict,
    row_b: dict,
    mapping: dict,
    distance_m: float,
    duration_s: float,
    source: str,
    buffer_m: int,
    margin_min: int = 15,
) -> str:
    def val(row, colkey, default="S/D"):
        col = mapping.get(colkey)
        return safe_text(row.get(col, default), default=default) if col else default

    fecha_a = f"{safe_text(row_a.get('__date', ''))} {safe_text(row_a.get('__time', ''))}".strip()
    fecha_b = f"{safe_text(row_b.get('__date', ''))} {safe_text(row_b.get('__time', ''))}".strip()
    tipo_a = safe_text(row_a.get("__tipo", "S/D"))
    tipo_b = safe_text(row_b.get("__tipo", "S/D"))
    az_a = val(row_a, "azimuth")
    az_b = val(row_b, "azimuth")

    return f"""
    <div style="font-family:Arial, Helvetica, sans-serif;min-width:380px;max-width:620px;">
      <div style="background:#064e3b;color:white;padding:10px 12px;border-radius:8px 8px 0 0;">
        <div style="font-size:16px;font-weight:700;">Ruta probable de búsqueda operativa</div>
        <div style="font-size:12px;opacity:.90;">{segment_name}</div>
      </div>
      <table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e5e7eb;">
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Evento origen</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{fecha_a} | {tipo_a} | Azimuth {az_a}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Evento destino</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{fecha_b} | {tipo_b} | Azimuth {az_b}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Tiempo entre eventos</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{_time_diff_label(row_a.get('__datetime'), row_b.get('__datetime'))}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Distancia vial aproximada</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{format_distance(distance_m)}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Tiempo de ruta estimado</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{format_duration(duration_s)}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Motor / fuente</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{safe_text(source)}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Corredor de búsqueda</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">±{int(buffer_m)} m</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Uso recomendado</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">Buscar cámaras, accesos, casetas, comercios, gasolineras, Oxxos, hoteles, restaurantes y testigos cercanos al corredor.</td></tr>
      </table>
      <div style="margin-top:10px;padding:8px;border-left:4px solid #0f766e;background:#ecfdf5;color:#134e4a;font-size:12px;">
        <b>Nota técnica:</b> Esta ruta fue generada como apoyo operativo entre puntos estimados dentro del sector de cobertura/azimuth de eventos CDR consecutivos.
        No representa por sí sola el trayecto exacto del equipo ni de una persona investigada.
      </div>
    </div>
    """


def _projected_point_for_route(row: dict, mapping: dict, options: KMZProOptions) -> Optional[tuple[float, float]]:
    """
    Regresa (lat, lon) para la ruta operativa.
    Usa centro del azimuth cuando existe; si no, usa coordenada de antena.
    """
    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    az_col = mapping.get("azimuth")

    lat = to_float(row.get(lat_col))
    lon = to_float(row.get(lon_col))
    if not valid_lat_lon(lat, lon):
        return None

    az = to_float(row.get(az_col)) if az_col else None
    if az is not None and 0 <= float(az) <= 360:
        try:
            from .kmz_pro_utils import bearing_destination
            dist = float(options.azimuth_radius_m) * float(options.route_azimuth_factor or 0.65)
            return bearing_destination(float(lat), float(lon), float(az), dist)
        except Exception:
            pass

    return float(lat), float(lon)



def _azimuth_value(row: dict, mapping: dict):
    az_col = mapping.get("azimuth")
    return to_float(row.get(az_col)) if az_col else None


def _antenna_latlon(row: dict, mapping: dict):
    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    lat = to_float(row.get(lat_col))
    lon = to_float(row.get(lon_col))
    if not valid_lat_lon(lat, lon):
        return None
    return float(lat), float(lon)


def _azimuth_projection(row: dict, mapping: dict, options: KMZProOptions):
    """
    Proyecta un punto dentro del eje del azimuth.
    Regresa dict con antena, azimuth y punto proyectado.
    """
    ant = _antenna_latlon(row, mapping)
    if not ant:
        return None

    lat, lon = ant
    az = _azimuth_value(row, mapping)

    proj_lat, proj_lon = lat, lon
    used_azimuth = False

    if az is not None and 0 <= float(az) <= 360:
        try:
            from .kmz_pro_utils import bearing_destination
            dist = float(options.azimuth_radius_m) * float(options.route_azimuth_factor or 0.65)
            proj_lat, proj_lon = bearing_destination(lat, lon, float(az), dist)
            used_azimuth = True
        except Exception:
            proj_lat, proj_lon = lat, lon

    return {
        "row": row,
        "antenna_lat": lat,
        "antenna_lon": lon,
        "projected_lat": float(proj_lat),
        "projected_lon": float(proj_lon),
        "azimuth": az,
        "used_azimuth": used_azimuth,
        "datetime": row.get("__datetime"),
        "date": row.get("__date", "SIN_FECHA"),
        "time": row.get("__time", ""),
        "tipo": row.get("__tipo", "S/D"),
    }


def _projection_key(item: dict) -> tuple:
    """
    Llave para consolidar eventos repetidos en el mismo sector.
    """
    az = item.get("azimuth")
    az_key = -1 if az is None else round(float(az), 0)
    return (
        round(float(item["antenna_lat"]), 6),
        round(float(item["antenna_lon"]), 6),
        az_key,
        round(float(item["projected_lat"]), 5),
        round(float(item["projected_lon"]), 5),
    )


def _consolidate_projection_items(items: list[dict]) -> list[dict]:
    """
    Une eventos consecutivos que caen en la misma antena/azimuth para evitar
    líneas de distancia 0 que no se ven en Google Earth.
    """
    if not items:
        return []

    out = []
    current = dict(items[0])
    current["count"] = 1
    current["first_row"] = items[0]["row"]
    current["last_row"] = items[0]["row"]

    for item in items[1:]:
        if _projection_key(item) == _projection_key(current):
            current["count"] += 1
            current["last_row"] = item["row"]
            current["row"] = item["row"]
            current["datetime"] = item.get("datetime")
            current["date"] = item.get("date")
            current["time"] = item.get("time")
            current["tipo"] = item.get("tipo")
        else:
            out.append(current)
            current = dict(item)
            current["count"] = 1
            current["first_row"] = item["row"]
            current["last_row"] = item["row"]

    out.append(current)
    return out


def _chain_event_label(item: dict, idx: int) -> str:
    az = item.get("azimuth")
    az_txt = "S/AZ" if az is None else f"Az {float(az):.0f}°"
    count = int(item.get("count", 1))
    count_txt = f" | {count} eventos" if count > 1 else ""
    return f"{idx:04d} | {safe_text(item.get('date'))} {safe_text(item.get('time'), '')} | {safe_text(item.get('tipo'))} | {az_txt}{count_txt}"


def _azimuth_chain_popup(item_a: dict, item_b: dict, idx_a: int, idx_b: int, mapping: dict) -> str:
    row_a = item_a.get("row", {})
    row_b = item_b.get("row", {})

    az_a = "S/D" if item_a.get("azimuth") is None else f"{float(item_a.get('azimuth')):.0f}°"
    az_b = "S/D" if item_b.get("azimuth") is None else f"{float(item_b.get('azimuth')):.0f}°"

    fecha_a = f"{safe_text(row_a.get('__date', ''))} {safe_text(row_a.get('__time', ''), '')}".strip()
    fecha_b = f"{safe_text(row_b.get('__date', ''))} {safe_text(row_b.get('__time', ''), '')}".strip()

    try:
        dist = polyline_distance_m([
            (float(item_a["projected_lon"]), float(item_a["projected_lat"])),
            (float(item_b["projected_lon"]), float(item_b["projected_lat"])),
        ])
    except Exception:
        dist = 0.0

    return f"""
    <div style="font-family:Arial, Helvetica, sans-serif;min-width:380px;max-width:620px;">
      <div style="background:#312e81;color:white;padding:10px 12px;border-radius:8px 8px 0 0;">
        <div style="font-size:16px;font-weight:700;">Enlace cronológico azimuth → azimuth</div>
        <div style="font-size:12px;opacity:.90;">Evento {idx_a:03d} → Evento {idx_b:03d}</div>
      </div>
      <table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e5e7eb;">
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Origen</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{fecha_a} | {safe_text(row_a.get('__tipo'))} | {az_a}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Destino</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{fecha_b} | {safe_text(row_b.get('__tipo'))} | {az_b}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Distancia directa entre zonas estimadas</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{format_distance(dist)}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Interpretación</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">Vínculo visual entre zonas estimadas dentro de sectores azimuth consecutivos.</td></tr>
      </table>
      <div style="margin-top:10px;padding:8px;border-left:4px solid #4f46e5;background:#eef2ff;color:#312e81;font-size:12px;">
        <b>Nota técnica:</b> Este enlace no afirma ruta exacta. Sirve para visualizar continuidad temporal entre sectores de cobertura/azimuth reportados por CDR.
      </div>
    </div>
    """


def _azimuth_point_popup(item: dict, idx: int, mapping: dict) -> str:
    row = item.get("row", {})
    az = "S/D" if item.get("azimuth") is None else f"{float(item.get('azimuth')):.0f}°"
    return f"""
    <div style="font-family:Arial, Helvetica, sans-serif;min-width:340px;max-width:540px;">
      <div style="background:#1d4ed8;color:white;padding:10px 12px;border-radius:8px 8px 0 0;">
        <div style="font-size:16px;font-weight:700;">Punto proyectado dentro del azimuth</div>
        <div style="font-size:12px;opacity:.90;">Secuencia {idx:03d}</div>
      </div>
      <table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e5e7eb;">
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Fecha/hora</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{safe_text(row.get('__date'))} {safe_text(row.get('__time'), '')}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Tipo</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{safe_text(row.get('__tipo'))}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Azimuth</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{az}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Eventos consolidados</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{int(item.get('count', 1))}</td></tr>
      </table>
      <div style="margin-top:10px;padding:8px;border-left:4px solid #2563eb;background:#eff6ff;color:#1e3a8a;font-size:12px;">
        Punto operativo calculado sobre el eje del azimuth. No representa ubicación exacta del equipo.
      </div>
    </div>
    """


def _last_antenna_popup(item: dict) -> str:
    row = item.get("row", {})
    return f"""
    <div style="font-family:Arial, Helvetica, sans-serif;min-width:340px;max-width:540px;">
      <div style="background:#7c2d12;color:white;padding:10px 12px;border-radius:8px 8px 0 0;">
        <div style="font-size:16px;font-weight:700;">Enlace final: último azimuth → última antena</div>
      </div>
      <table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e5e7eb;">
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Último evento</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{safe_text(row.get('__date'))} {safe_text(row.get('__time'), '')}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Tipo</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{safe_text(row.get('__tipo'))}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Uso</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">Referencia visual para cerrar la secuencia en la última celda/antena reportada.</td></tr>
      </table>
    </div>
    """


def _add_azimuth_chain(kml, df: pd.DataFrame, mapping: dict, options: KMZProOptions):
    """
    Crea una capa explícita de comunicación/continuidad:
    azimuth proyectado → azimuth proyectado → última antena.
    """
    if str(getattr(options, "route_mode", "")).lower() != "enlace_azimuth":
        return

    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    if not lat_col or not lon_col:
        return

    mappable = df[df["__is_mappable"]].copy() if "__is_mappable" in df.columns else df.copy()
    if mappable.empty:
        return

    if "__datetime" in mappable.columns:
        mappable = mappable.sort_values("__datetime")

    root = kml.newfolder(name="05_Enlace cronológico azimuth a azimuth")
    line_folder = root.newfolder(name="Enlaces azimuth → azimuth")
    point_folder = root.newfolder(name="Puntos proyectados dentro del azimuth")
    last_folder = root.newfolder(name="Último azimuth → última antena")
    stay_folder = root.newfolder(name="Permanencias / mismo sector")

    for day, gday in mappable.groupby("__date", dropna=False):
        gday = gday.sort_values("__datetime") if "__datetime" in gday.columns else gday

        items = []
        for _, row in gday.iterrows():
            item = _azimuth_projection(row.to_dict(), mapping, options)
            if item:
                items.append(item)

        if getattr(options, "consolidate_same_azimuth_sector", True):
            items = _consolidate_projection_items(items)

        if int(getattr(options, "azimuth_chain_max_points", 300)) > 0:
            items = items[: int(options.azimuth_chain_max_points)]

        if len(items) < 1:
            continue

        if getattr(options, "show_azimuth_chain_points", True):
            for idx, item in enumerate(items, start=1):
                p = point_folder.newpoint(
                    name=_chain_event_label(item, idx),
                    coords=[(float(item["projected_lon"]), float(item["projected_lat"]))],
                )
                p.description = _azimuth_point_popup(item, idx, mapping)
                apply_icon_style(p, COLOR_BLUE, ICON_URLS["event"], scale=0.8, label_scale=0.0)

        if len(items) >= 2:
            # Línea general del día para que se vea la continuidad completa.
            coords_all = [(float(it["projected_lon"]), float(it["projected_lat"])) for it in items]
            day_line = line_folder.newlinestring(
                name=f"Secuencia completa azimuth → azimuth | {day}",
                coords=coords_all,
            )
            day_line.description = f"""
            <b>Secuencia completa azimuth → azimuth</b><br>
            Fecha: {day}<br>
            Puntos conectados: {len(coords_all)}<br>
            Nota: conecta puntos proyectados dentro de sectores azimuth en orden cronológico.
            """
            apply_line_style(day_line, COLOR_PURPLE, width=max(4, int(options.route_width) + 1))

            for idx in range(len(items) - 1):
                a = items[idx]
                b = items[idx + 1]
                coords = [
                    (float(a["projected_lon"]), float(a["projected_lat"])),
                    (float(b["projected_lon"]), float(b["projected_lat"])),
                ]
                dist = polyline_distance_m(coords)

                if dist < 10:
                    # Línea muy pequeña no se aprecia. Se crea un círculo de permanencia.
                    poly = stay_folder.newpolygon(
                        name=f"Mismo sector / permanencia | {day} | {idx+1:03d} → {idx+2:03d}",
                        outerboundaryis=circle_coords(float(a["projected_lat"]), float(a["projected_lon"]), 60, steps=36),
                    )
                    poly.description = _azimuth_chain_popup(a, b, idx + 1, idx + 2, mapping)
                    apply_polygon_style(poly, COLOR_ORANGE, POLY_CYAN_TRANSPARENT, line_width=2)
                else:
                    line = line_folder.newlinestring(
                        name=f"Enlace azimuth → azimuth | {day} | {idx+1:03d} → {idx+2:03d}",
                        coords=coords,
                    )
                    line.description = _azimuth_chain_popup(a, b, idx + 1, idx + 2, mapping)
                    apply_line_style(line, COLOR_LIME, width=max(3, int(options.route_width)))

        if getattr(options, "link_last_azimuth_to_last_antenna", True) and items:
            last = items[-1]
            coords = [
                (float(last["projected_lon"]), float(last["projected_lat"])),
                (float(last["antenna_lon"]), float(last["antenna_lat"])),
            ]
            line = last_folder.newlinestring(
                name=f"Último azimuth → última antena | {day}",
                coords=coords,
            )
            line.description = _last_antenna_popup(last)
            apply_line_style(line, COLOR_ORANGE, width=max(3, int(options.route_width)))



def _azimuth_road_popup(
    segment_name: str,
    item_a: dict,
    item_b: dict,
    idx_a: int,
    idx_b: int,
    distance_m: float,
    duration_s: float,
    source: str,
    buffer_m: int,
    margin_min: int = 15,
) -> str:
    row_a = item_a.get("row", {})
    row_b = item_b.get("row", {})

    az_a = "S/D" if item_a.get("azimuth") is None else f"{float(item_a.get('azimuth')):.0f}°"
    az_b = "S/D" if item_b.get("azimuth") is None else f"{float(item_b.get('azimuth')):.0f}°"

    fecha_a = f"{safe_text(row_a.get('__date', ''))} {safe_text(row_a.get('__time', ''), '')}".strip()
    fecha_b = f"{safe_text(row_b.get('__date', ''))} {safe_text(row_b.get('__time', ''), '')}".strip()
    ventana = _camera_search_window(row_a, row_b, margin_min)

    return f"""
    <div style="font-family:Arial, Helvetica, sans-serif;min-width:390px;max-width:640px;">
      <div style="background:#14532d;color:white;padding:10px 12px;border-radius:8px 8px 0 0;">
        <div style="font-size:16px;font-weight:700;">Ruta vial azimuth → azimuth</div>
        <div style="font-size:12px;opacity:.90;">{segment_name}</div>
      </div>
      <table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e5e7eb;">
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Origen proyectado</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">Evento {idx_a:03d} | {fecha_a} | {safe_text(row_a.get('__tipo'))} | {az_a}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Destino proyectado</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">Evento {idx_b:03d} | {fecha_b} | {safe_text(row_b.get('__tipo'))} | {az_b}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Hora evento origen</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["evento_origen"]}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Hora evento destino</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["evento_destino"]}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Tiempo entre eventos CDR</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{_time_diff_label(row_a.get('__datetime'), row_b.get('__datetime'))}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Rango base de revisión</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["rango_base"]}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Rango sugerido con margen</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["rango_margen"]} ({ventana["margen"]})</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Distancia vial calculada</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{format_distance(distance_m)}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Tiempo vial estimado</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{format_duration(duration_s)}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Motor / fuente</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{safe_text(source)}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Corredor sugerido</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">±{int(buffer_m)} m</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Uso operativo</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">Orientar búsqueda de cámaras, negocios, accesos, casetas, testigos y puntos de paso cercanos a la ruta vial.</td></tr>
      </table>
      <div style="margin-top:10px;padding:8px;border-left:4px solid #16a34a;background:#f0fdf4;color:#14532d;font-size:12px;">
        <b>Nota técnica:</b> Ruta vial calculada entre puntos estimados dentro de sectores azimuth consecutivos.
        Es una guía operativa para búsqueda de evidencia externa; no afirma el trayecto real ni ubicación exacta del equipo.
      </div>
    </div>
    """



def _osm_business_popup(poi: dict, segment_name: str, item_a: dict, item_b: dict, options: KMZProOptions) -> str:
    row_a = item_a.get("row", {})
    row_b = item_b.get("row", {})
    ventana = _camera_search_window(row_a, row_b, int(getattr(options, "camera_search_margin_min", 15)))
    name = safe_text(poi.get("name"))
    category = safe_text(poi.get("category"))
    distance_txt = format_distance(poi.get("distance_m", 0))
    return f"""
    <div style="font-family:Arial, Helvetica, sans-serif;min-width:390px;max-width:620px;">
      <div style="background:#164e63;color:white;padding:10px 12px;border-radius:8px 8px 0 0;">
        <div style="font-size:16px;font-weight:700;">Negocio/empresa sugerida para búsqueda de cámaras</div>
        <div style="font-size:12px;opacity:.90;">Fuente: OpenStreetMap / Overpass</div>
      </div>
      <table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e5e7eb;">
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Nombre</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{name}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Tipo</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{category}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Segmento</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{segment_name}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Distancia a la ruta/corredor</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{distance_txt}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Hora evento origen</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["evento_origen"]}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Hora evento destino</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["evento_destino"]}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Buscar video entre</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["rango_base"]}</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Buscar con margen operativo</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["rango_margen"]} ({ventana["margen"]})</td></tr>
        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Uso recomendado</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">Verificar cámaras, responsables, accesos, horarios de operación, testigos y conservación de video.</td></tr>
      </table>
      <div style="margin-top:10px;padding:8px;border-left:4px solid #0e7490;background:#ecfeff;color:#164e63;font-size:12px;">
        <b>Nota:</b> Este punto proviene de OpenStreetMap y se ubica dentro del corredor operativo configurado. Debe confirmarse mediante inspección visual/física por los investigadores.
      </div>
    </div>
    """

def _add_azimuth_road_routes(kml, df: pd.DataFrame, mapping: dict, options: KMZProOptions):
    """
    Crea rutas por calles entre puntos proyectados dentro del azimuth.
    Esta es la capa buscada para aproximarse visualmente al ejemplo tipo Dijkstra:
    no conecta antena-antena ni punto-punto con línea recta, sino que consulta
    una ruta vial OSRM entre el punto proyectado del evento A y el punto proyectado del evento B.
    """
    if str(getattr(options, "route_mode", "")).lower() != "ruta_vial_azimuth":
        return

    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    if not lat_col or not lon_col:
        return

    mappable = df[df["__is_mappable"]].copy() if "__is_mappable" in df.columns else df.copy()
    if mappable.empty:
        return

    if "__datetime" in mappable.columns:
        mappable = mappable.sort_values("__datetime")

    root = kml.newfolder(name="05_Ruta vial azimuth a azimuth")
    route_folder = root.newfolder(name="Rutas por calles entre azimuths")
    points_folder = root.newfolder(name="Puntos proyectados del azimuth")
    corridor_folder = root.newfolder(name=f"Corredor de búsqueda ±{int(options.azimuth_road_buffer_m)}m")
    camera_folder = root.newfolder(name=f"Puntos sugeridos para cámaras cada {int(options.azimuth_road_camera_interval_m)}m")
    osm_folder = root.newfolder(name="Negocios/empresas sugeridas para cámaras (OSM)")
    ref_folder = root.newfolder(name="Líneas directas de referencia")

    total_segments = 0

    for day, gday in mappable.groupby("__date", dropna=False):
        gday = gday.sort_values("__datetime") if "__datetime" in gday.columns else gday

        items = []
        for _, row in gday.iterrows():
            item = _azimuth_projection(row.to_dict(), mapping, options)
            if item:
                items.append(item)

        if getattr(options, "consolidate_same_azimuth_sector", True):
            items = _consolidate_projection_items(items)

        if int(getattr(options, "azimuth_chain_max_points", 300)) > 0:
            items = items[: int(options.azimuth_chain_max_points)]

        if len(items) < 1:
            continue

        # Puntos proyectados para que se vea de dónde sale la ruta vial.
        if getattr(options, "show_azimuth_chain_points", True):
            for idx, item in enumerate(items, start=1):
                p = points_folder.newpoint(
                    name=_chain_event_label(item, idx),
                    coords=[(float(item["projected_lon"]), float(item["projected_lat"]))],
                )
                p.description = _azimuth_point_popup(item, idx, mapping)
                apply_icon_style(p, COLOR_BLUE, ICON_URLS["event"], scale=0.8, label_scale=0.0)

        if len(items) < 2:
            continue

        full_coords = []

        for idx in range(len(items) - 1):
            if total_segments >= int(options.max_azimuth_road_segments):
                break

            a = items[idx]
            b = items[idx + 1]

            lat_a = float(a["projected_lat"])
            lon_a = float(a["projected_lon"])
            lat_b = float(b["projected_lat"])
            lon_b = float(b["projected_lon"])

            route = osrm_route(
                lat_a,
                lon_a,
                lat_b,
                lon_b,
                profile=options.osrm_profile,
                timeout=int(options.osrm_timeout_s),
            )

            if route and route.get("coords"):
                coords = route["coords"]
                dist = float(route.get("distance_m") or polyline_distance_m(coords))
                dur = float(route.get("duration_s") or 0.0)
                source = route.get("source", "OSRM")
            else:
                coords = [(lon_a, lat_a), (lon_b, lat_b)]
                dist = polyline_distance_m(coords)
                dur = 0.0
                source = "Fallback línea directa"

            segment_name = f"{day} | Segmento {idx+1:03d} → {idx+2:03d}"
            popup = _azimuth_road_popup(
                segment_name,
                a,
                b,
                idx + 1,
                idx + 2,
                dist,
                dur,
                source,
                int(options.azimuth_road_buffer_m),
                int(getattr(options, "camera_search_margin_min", 15)),
            )

            line = route_folder.newlinestring(
                name=f"Ruta por calles azimuth → azimuth | {segment_name}",
                coords=coords,
            )
            line.description = popup
            route_color = getattr(options, "azimuth_road_route_color", COLOR_LIME) or COLOR_LIME
            apply_line_style(line, route_color, width=max(5, int(options.route_width) + 2))

            if getattr(options, "draw_full_azimuth_road_sequence", True) and coords:
                if not full_coords:
                    full_coords.extend(coords)
                else:
                    # Evitar duplicar el punto inicial si coincide.
                    full_coords.extend(coords[1:] if len(coords) > 1 else coords)

            if options.show_azimuth_road_direct_reference:
                ref = ref_folder.newlinestring(
                    name=f"Referencia directa azimuth → azimuth | {segment_name}",
                    coords=[(lon_a, lat_a), (lon_b, lat_b)],
                )
                ref.description = popup
                apply_line_style(ref, COLOR_CYAN, width=2)

            if options.show_azimuth_road_corridor:
                poly_coords = corridor_polygon(coords, float(options.azimuth_road_buffer_m))
                if len(poly_coords) >= 4:
                    poly = corridor_folder.newpolygon(
                        name=f"Corredor búsqueda cámaras | {segment_name}",
                        outerboundaryis=poly_coords,
                    )
                    poly.description = popup
                    apply_polygon_style(poly, COLOR_CYAN, POLY_CYAN_TRANSPARENT, line_width=1)


            # Negocios/empresas reales desde OpenStreetMap dentro del corredor.
            # No se agregan puntos genéricos si no existen resultados OSM.
            if getattr(options, "show_osm_business_camera_points", True):
                pois = overpass_business_pois_near_route(
                    coords,
                    buffer_m=float(options.azimuth_road_buffer_m),
                    timeout=int(getattr(options, "osm_business_timeout_s", 18)),
                    max_results=int(getattr(options, "osm_business_max_per_segment", 25)),
                )
                for poi in pois:
                    p_osm = osm_folder.newpoint(
                        name=f"{poi.get('name', 'Negocio/empresa')} | {segment_name}",
                        coords=[(float(poi["lon"]), float(poi["lat"]))],
                    )
                    p_osm.description = _osm_business_popup(poi, segment_name, a, b, options)
                    apply_icon_style(p_osm, COLOR_ORANGE, ICON_URLS["star"], scale=0.85, label_scale=0.0)

            if options.show_azimuth_road_camera_points:
                pts = sample_points_along_line(coords, float(options.azimuth_road_camera_interval_m), include_ends=True)
                if len(pts) > 80:
                    step = max(1, len(pts) // 80)
                    pts = pts[::step] + [pts[-1]]

                for j, (lonp, latp) in enumerate(pts, start=1):
                    pnt = camera_folder.newpoint(
                        name=f"Cámara/verificación sugerida {j:03d} | {segment_name}",
                        coords=[(float(lonp), float(latp))],
                    )
                    ventana = _camera_search_window(
                        a.get("row", {}),
                        b.get("row", {}),
                        int(getattr(options, "camera_search_margin_min", 15)),
                    )

                    pnt.description = f"""
                    <div style="font-family:Arial, Helvetica, sans-serif;min-width:380px;max-width:590px;">
                      <div style="background:#78350f;color:white;padding:9px 11px;border-radius:8px 8px 0 0;">
                        <b>Punto sugerido para búsqueda de cámaras</b>
                      </div>
                      <table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e5e7eb;">
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Segmento</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{segment_name}</td></tr>
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Hora evento origen</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["evento_origen"]}</td></tr>
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Hora evento destino</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["evento_destino"]}</td></tr>
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Buscar video entre</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["rango_base"]}</td></tr>
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Buscar con margen operativo</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["rango_margen"]} ({ventana["margen"]})</td></tr>
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Uso recomendado</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">Verificar cámaras públicas/privadas, comercios, accesos, casetas, gasolineras, Oxxos, hoteles, restaurantes y testigos cercanos.</td></tr>
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Corredor</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">±{int(options.azimuth_road_buffer_m)} m</td></tr>
                      </table>
                      <div style="margin-top:10px;padding:8px;border-left:4px solid #92400e;background:#fffbeb;color:#78350f;font-size:12px;">
                        Punto de apoyo operativo. No representa ubicación exacta del equipo.
                      </div>
                    </div>
                    """
                    apply_icon_style(pnt, COLOR_ORANGE, ICON_URLS["star"], scale=0.7, label_scale=0.0)

            total_segments += 1

        if getattr(options, "draw_full_azimuth_road_sequence", True) and len(full_coords) >= 2:
            full_line = route_folder.newlinestring(
                name=f"Secuencia vial completa azimuth → azimuth | {day}",
                coords=full_coords,
            )
            full_line.description = f"""
            <b>Secuencia vial completa azimuth → azimuth</b><br>
            Fecha: {day}<br>
            Puntos de ruta: {len(full_coords)}<br>
            Nota: unión de segmentos viales calculados entre puntos proyectados dentro de azimuths consecutivos.
            """
            route_color = getattr(options, "azimuth_road_route_color", COLOR_LIME) or COLOR_LIME
            apply_line_style(full_line, route_color, width=max(6, int(options.route_width) + 3))


def _route_coords_from_df(df: pd.DataFrame, mapping: dict, options: KMZProOptions):
    """
    Construye coordenadas para la ruta temporal.

    route_mode="antena":
        conecta directamente las coordenadas de antena reportadas en CDR.

    route_mode="centro_azimuth":
        cuando existe azimuth, no conecta antena con antena; calcula un punto
        dentro del sector de cobertura, sobre el eje del azimuth, y conecta esos
        puntos estimados. Esto es visualmente más coherente para análisis operativo,
        pero sigue siendo una aproximación, no ubicación exacta del equipo.
    """
    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    az_col = mapping.get("azimuth")

    coords = []
    mode = str(getattr(options, "route_mode", "antena") or "antena").lower()

    for _, row in df.iterrows():
        lat = to_float(row.get(lat_col))
        lon = to_float(row.get(lon_col))
        if not valid_lat_lon(lat, lon):
            continue

        out_lat, out_lon = float(lat), float(lon)

        if mode == "centro_azimuth" and az_col and az_col in df.columns:
            az = to_float(row.get(az_col))
            if az is not None and 0 <= float(az) <= 360:
                try:
                    from .kmz_pro_utils import bearing_destination
                    dist = float(options.azimuth_radius_m) * float(options.route_azimuth_factor or 0.65)
                    out_lat, out_lon = bearing_destination(float(lat), float(lon), float(az), dist)
                except Exception:
                    out_lat, out_lon = float(lat), float(lon)

        coords.append((float(out_lon), float(out_lat)))

    return coords


def _add_routes(kml, df: pd.DataFrame, mapping: dict, options: KMZProOptions):
    if not options.show_routes_by_day:
        return

    # En modo ruta operativa se crea una carpeta especializada con ruta vial,
    # corredor de búsqueda y puntos sugeridos para cámaras.
    if str(getattr(options, "route_mode", "")).lower() in {"ruta_operativa_osrm", "enlace_azimuth", "ruta_vial_azimuth"}:
        return

    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    if not lat_col or not lon_col:
        return

    mappable = df[df["__is_mappable"]].copy() if "__is_mappable" in df.columns else df.copy()
    if mappable.empty:
        return
    if "__datetime" in mappable.columns:
        mappable = mappable.sort_values("__datetime")

    root = kml.newfolder(name="03_Rutas temporales")

    for day, gday in mappable.groupby("__date", dropna=False):
        coords = _route_coords_from_df(gday, mapping, options)
        if len(coords) < 2:
            continue

        route_mode = str(getattr(options, "route_mode", "antena") or "antena").lower()
        mode_label = "centro del azimuth / área probable" if route_mode == "centro_azimuth" else "antena a antena"

        line = root.newlinestring(name=f"Ruta cronológica ({mode_label}) | {day}", coords=coords)
        line.description = f"""
        <b>Ruta cronológica</b><br>
        Fecha: {day}<br>
        Modo: {mode_label}<br>
        Puntos conectados: {len(coords)}<br>
        Nota: línea referencial entre eventos ordenados por fecha y hora. En modo centro del azimuth,
        la línea conecta puntos estimados dentro del sector de cobertura y no debe interpretarse
        como recorrido exacto del equipo.
        """
        apply_line_style(line, COLOR_PURPLE, width=options.route_width)


def _add_operational_routes(kml, df: pd.DataFrame, mapping: dict, options: KMZProOptions):
    """
    Agrega ruta vial probable para búsqueda de cámaras/evidencia.
    """
    if str(getattr(options, "route_mode", "")).lower() != "ruta_operativa_osrm":
        return

    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    if not lat_col or not lon_col:
        return

    mappable = df[df["__is_mappable"]].copy() if "__is_mappable" in df.columns else df.copy()
    if mappable.empty:
        return
    if "__datetime" in mappable.columns:
        mappable = mappable.sort_values("__datetime")

    root = kml.newfolder(name="05_Ruta probable de búsqueda operativa")
    route_folder = root.newfolder(name="Rutas viales aproximadas")
    corridor_folder = root.newfolder(name=f"Corredor de búsqueda ±{int(options.operational_route_buffer_m)}m")
    points_folder = root.newfolder(name=f"Puntos sugeridos para cámaras cada {int(options.camera_search_interval_m)}m")
    ref_folder = root.newfolder(name="Líneas directas de referencia")

    total_segments = 0

    for day, gday in mappable.groupby("__date", dropna=False):
        gday = gday.sort_values("__datetime") if "__datetime" in gday.columns else gday
        rows = [r.to_dict() for _, r in gday.iterrows()]
        if len(rows) < 2:
            continue

        for i in range(len(rows) - 1):
            if total_segments >= int(options.max_operational_segments):
                return

            row_a = rows[i]
            row_b = rows[i + 1]
            p_a = _projected_point_for_route(row_a, mapping, options)
            p_b = _projected_point_for_route(row_b, mapping, options)
            if not p_a or not p_b:
                continue

            lat_a, lon_a = p_a
            lat_b, lon_b = p_b

            route = osrm_route(
                lat_a,
                lon_a,
                lat_b,
                lon_b,
                profile=options.osrm_profile,
                timeout=int(options.osrm_timeout_s),
            )

            if route and route.get("coords"):
                coords = route["coords"]
                dist = float(route.get("distance_m") or polyline_distance_m(coords))
                dur = float(route.get("duration_s") or 0.0)
                source = route.get("source", "OSRM")
            else:
                coords = [(lon_a, lat_a), (lon_b, lat_b)]
                dist = polyline_distance_m(coords)
                dur = 0.0
                source = "Fallback línea directa"

            segment_name = f"{day} | Segmento {i+1:03d} → {i+2:03d}"
            popup = _operational_route_popup(
                segment_name,
                row_a,
                row_b,
                mapping,
                dist,
                dur,
                source,
                int(options.operational_route_buffer_m),
            )

            line = route_folder.newlinestring(
                name=f"Ruta vial probable | {segment_name}",
                coords=coords,
            )
            line.description = popup
            apply_line_style(line, COLOR_LIME, width=max(4, int(options.route_width) + 2))

            if options.show_direct_reference_line and len(coords) >= 2:
                ref = ref_folder.newlinestring(
                    name=f"Referencia directa | {segment_name}",
                    coords=[(lon_a, lat_a), (lon_b, lat_b)],
                )
                ref.description = popup
                apply_line_style(ref, COLOR_CYAN, width=2)

            if options.show_operational_route_corridor:
                poly_coords = corridor_polygon(coords, float(options.operational_route_buffer_m))
                if len(poly_coords) >= 4:
                    poly = corridor_folder.newpolygon(
                        name=f"Corredor operativo | {segment_name}",
                        outerboundaryis=poly_coords,
                    )
                    poly.description = popup
                    apply_polygon_style(poly, COLOR_CYAN, POLY_CYAN_TRANSPARENT, line_width=1)

            if options.show_camera_search_points:
                pts = sample_points_along_line(coords, float(options.camera_search_interval_m), include_ends=True)
                # Limita por segmento para no hacer KMZ enorme
                if len(pts) > 80:
                    step = max(1, len(pts) // 80)
                    pts = pts[::step] + [pts[-1]]

                for j, (lonp, latp) in enumerate(pts, start=1):
                    pnt = points_folder.newpoint(
                        name=f"Cámara/verificación sugerida {j:03d} | {segment_name}",
                        coords=[(float(lonp), float(latp))],
                    )
                    ventana = _camera_search_window(
                        row_a,
                        row_b,
                        int(getattr(options, "camera_search_margin_min", 15)),
                    )

                    pnt.description = f"""
                    <div style="font-family:Arial, Helvetica, sans-serif;min-width:380px;max-width:590px;">
                      <div style="background:#78350f;color:white;padding:9px 11px;border-radius:8px 8px 0 0;">
                        <b>Punto sugerido para búsqueda de cámaras</b>
                      </div>
                      <table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e5e7eb;">
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Segmento</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{segment_name}</td></tr>
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Hora evento origen</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["evento_origen"]}</td></tr>
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Hora evento destino</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["evento_destino"]}</td></tr>
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Buscar video entre</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["rango_base"]}</td></tr>
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Buscar con margen operativo</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">{ventana["rango_margen"]} ({ventana["margen"]})</td></tr>
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Uso recomendado</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">Verificar cámaras públicas/privadas, comercios, accesos, casetas y testigos cercanos.</td></tr>
                        <tr><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;"><b>Corredor</b></td><td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;">±{int(options.operational_route_buffer_m)} m</td></tr>
                      </table>
                      <div style="margin-top:10px;padding:8px;border-left:4px solid #92400e;background:#fffbeb;color:#78350f;font-size:12px;">
                        Punto de apoyo operativo. No representa ubicación exacta del equipo.
                      </div>
                    </div>
                    """
                    apply_icon_style(pnt, COLOR_ORANGE, ICON_URLS["star"], scale=0.7, label_scale=0.0)

            total_segments += 1


def _add_relevant(kml, df: pd.DataFrame, mapping: dict, options: KMZProOptions):
    if not options.show_relevant_events:
        return

    lat_col = mapping.get("latitud")
    lon_col = mapping.get("longitud")
    if not lat_col or not lon_col:
        return

    items = relevant_events(df, mapping)
    if not items:
        return

    root = kml.newfolder(name="04_Eventos relevantes detectados")

    for i, item in enumerate(items, start=1):
        row = item["row"]
        motivo = item["motivo"]
        lat = to_float(row.get(lat_col))
        lon = to_float(row.get(lon_col))
        if not valid_lat_lon(lat, lon):
            continue

        p = root.newpoint(
            name=f"{i:03d} | {motivo}",
            coords=[(float(lon), float(lat))]
        )
        p.description = relevant_popup("Sentinel Mapper KMZ Pro", row, mapping, motivo, modo=options.modo)
        apply_icon_style(p, COLOR_ORANGE, ICON_URLS["star"], scale=1.05, label_scale=0.75)


def build_kmz_pro(
    df: pd.DataFrame,
    options: Optional[KMZProOptions] = None,
    mapping: Optional[dict] = None,
    kmz_assets: Optional[dict[str, bytes]] = None,
) -> tuple[bytes, str, dict, pd.DataFrame]:
    """
    Construye KMZ y regresa:
    (kmz_bytes, filename, mapping, prepared_df)
    """
    if simplekml is None:
        raise RuntimeError("No se encontró simplekml. Instala con: pip install simplekml")

    if options is None:
        options = KMZProOptions()

    if mapping is None:
        mapping = detect_mapping(df)

    required = ["latitud", "longitud"]
    missing = [r for r in required if not mapping.get(r)]
    if missing:
        raise ValueError(f"No se detectaron columnas requeridas: {', '.join(missing)}")

    work = prepare_dataframe(df, mapping)

    kml = simplekml.Kml(name=options.case_title)
    doc = kml.document
    doc.name = options.case_title

    _add_summary(kml, work, mapping, options)
    _add_antenna_layers(kml, work, mapping, options)
    _add_events(kml, work, mapping, options)
    _add_routes(kml, work, mapping, options)
    _add_azimuth_chain(kml, work, mapping, options)
    _add_azimuth_road_routes(kml, work, mapping, options)
    _add_operational_routes(kml, work, mapping, options)
    _add_relevant(kml, work, mapping, options)

    telefono = "sentinel_mapper_kmz_pro"
    tel_col = mapping.get("telefono")
    if tel_col and tel_col in work.columns and not work[tel_col].dropna().empty:
        telefono = str(work[tel_col].dropna().iloc[0])

    filename = safe_filename(f"{telefono}_Sentinel_Mapper_KMZ_Pro.kmz")

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / filename
        kml.savekmz(str(out_path))

        # Incrusta iconos personalizados dentro del KMZ.
        # Los estilos KML deben referenciar las mismas rutas internas, por ejemplo:
        # files/antenna_icon.png o files/compass_icon.png
        if kmz_assets:
            with zipfile.ZipFile(out_path, "a", zipfile.ZIP_DEFLATED) as zf:
                for internal_path, data in kmz_assets.items():
                    if not internal_path or not data:
                        continue
                    zf.writestr(internal_path, data)

        kmz_bytes = out_path.read_bytes()

    return kmz_bytes, filename, mapping, work
