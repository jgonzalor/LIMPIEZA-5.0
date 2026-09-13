# -*- coding: utf-8 -*-
"""
Motor de construcción KMZ para Sentinel Mapper KMZ Pro.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import tempfile
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
    COLOR_GRAY,
    COLOR_ORANGE,
    COLOR_PURPLE,
    COLOR_WHITE,
    ICON_URLS,
    POLY_BLUE_TRANSPARENT,
    POLY_GRAY_TRANSPARENT,
    apply_icon_style,
    apply_line_style,
    apply_polygon_style,
    get_event_style,
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
    apply_icon_style(p, COLOR_BLACK, ICON_URLS["info"], scale=1.2, label_scale=0.9)


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
        apply_icon_style(p, COLOR_BLACK, ICON_URLS["antenna"], scale=1.05, label_scale=0.75)

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
            # Norte y ejes cardinales como líneas simples; evita depender de imágenes externas.
            for label, bearing, color, width in [
                ("N", 0, COLOR_BLACK, 3),
                ("E", 90, COLOR_GRAY, 1),
                ("S", 180, COLOR_GRAY, 1),
                ("W", 270, COLOR_GRAY, 1),
            ]:
                from .kmz_pro_utils import bearing_destination
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
        apply_icon_style(p, sty["color"], sty["icon"], scale=0.9, label_scale=0.55)


def _add_routes(kml, df: pd.DataFrame, mapping: dict, options: KMZProOptions):
    if not options.show_routes_by_day:
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
        coords = line_coords_from_df(gday, lat_col, lon_col)
        if len(coords) < 2:
            continue

        line = root.newlinestring(name=f"Ruta cronológica | {day}", coords=coords)
        line.description = f"""
        <b>Ruta cronológica</b><br>
        Fecha: {day}<br>
        Puntos conectados: {len(coords)}<br>
        Nota: línea referencial entre antenas/eventos ordenados por fecha y hora.
        """
        apply_line_style(line, COLOR_PURPLE, width=options.route_width)


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
    _add_relevant(kml, work, mapping, options)

    telefono = "sentinel_mapper_kmz_pro"
    tel_col = mapping.get("telefono")
    if tel_col and tel_col in work.columns and not work[tel_col].dropna().empty:
        telefono = str(work[tel_col].dropna().iloc[0])

    filename = safe_filename(f"{telefono}_Sentinel_Mapper_KMZ_Pro.kmz")

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / filename
        kml.savekmz(str(out_path))
        kmz_bytes = out_path.read_bytes()

    return kmz_bytes, filename, mapping, work
