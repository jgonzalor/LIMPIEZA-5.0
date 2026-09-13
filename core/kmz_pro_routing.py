# -*- coding: utf-8 -*-
"""
Ruteo operativo para Sentinel Mapper KMZ Pro.

Objetivo:
- Generar una ruta vial aproximada entre puntos estimados dentro del azimuth.
- Crear corredor de búsqueda para cámaras y puntos sugeridos de verificación.

Nota:
La ruta generada es una guía operativa para búsqueda de evidencia externa.
No representa por sí sola el trayecto real de una persona o dispositivo.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

import requests


EARTH_RADIUS_M = 6371008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(float(lat1))
    p2 = math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def polyline_distance_m(coords_lonlat: list[tuple[float, float]]) -> float:
    if len(coords_lonlat) < 2:
        return 0.0
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords_lonlat[:-1], coords_lonlat[1:]):
        total += haversine_m(lat1, lon1, lat2, lon2)
    return total


def osrm_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    profile: str = "driving",
    timeout: int = 8,
) -> Optional[dict]:
    """
    Consulta OSRM público.

    Regresa:
    {
      "coords": [(lon, lat), ...],
      "distance_m": float,
      "duration_s": float,
      "source": "OSRM"
    }

    Si falla, regresa None.
    """
    profile = str(profile or "driving").strip().lower()
    if profile not in {"driving", "walking", "cycling"}:
        profile = "driving"

    url = (
        f"https://router.project-osrm.org/route/v1/{profile}/"
        f"{float(start_lon)},{float(start_lat)};{float(end_lon)},{float(end_lat)}"
    )
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
        "alternatives": "false",
    }

    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        routes = data.get("routes") or []
        if not routes:
            return None

        route = routes[0]
        coords = route.get("geometry", {}).get("coordinates") or []
        clean = []
        for item in coords:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            lon, lat = float(item[0]), float(item[1])
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                clean.append((lon, lat))

        if len(clean) < 2:
            return None

        return {
            "coords": clean,
            "distance_m": float(route.get("distance") or polyline_distance_m(clean)),
            "duration_s": float(route.get("duration") or 0.0),
            "source": "OSRM",
        }
    except Exception:
        return None


def _meters_per_degree(lat0: float) -> tuple[float, float]:
    lat_rad = math.radians(float(lat0))
    m_per_deg_lat = 111_132.92 - 559.82 * math.cos(2 * lat_rad) + 1.175 * math.cos(4 * lat_rad)
    m_per_deg_lon = 111_412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad)
    if abs(m_per_deg_lon) < 1:
        m_per_deg_lon = 111_320.0
    return m_per_deg_lat, m_per_deg_lon


def _lonlat_to_xy(lon: float, lat: float, lat0: float, lon0: float) -> tuple[float, float]:
    mlat, mlon = _meters_per_degree(lat0)
    return (float(lon) - float(lon0)) * mlon, (float(lat) - float(lat0)) * mlat


def _xy_to_lonlat(x: float, y: float, lat0: float, lon0: float) -> tuple[float, float]:
    mlat, mlon = _meters_per_degree(lat0)
    return float(lon0) + float(x) / mlon, float(lat0) + float(y) / mlat


def corridor_polygon(coords_lonlat: list[tuple[float, float]], buffer_m: float = 100.0) -> list[tuple[float, float]]:
    """
    Crea un polígono corredor aproximado alrededor de una polilínea.

    Es un buffer simple local sin dependencia de Shapely.
    Suficiente para visualización KMZ operativa.
    """
    if len(coords_lonlat) < 2:
        return []

    # Simplificación ligera para evitar polígonos enormes.
    max_vertices = 160
    if len(coords_lonlat) > max_vertices:
        step = max(1, len(coords_lonlat) // max_vertices)
        coords_lonlat = coords_lonlat[::step] + [coords_lonlat[-1]]

    lon0 = sum(c[0] for c in coords_lonlat) / len(coords_lonlat)
    lat0 = sum(c[1] for c in coords_lonlat) / len(coords_lonlat)
    pts = [_lonlat_to_xy(lon, lat, lat0, lon0) for lon, lat in coords_lonlat]

    left = []
    right = []

    for i, (x, y) in enumerate(pts):
        normals = []
        if i > 0:
            x0, y0 = pts[i - 1]
            dx, dy = x - x0, y - y0
            length = math.hypot(dx, dy)
            if length > 0:
                normals.append((-dy / length, dx / length))
        if i < len(pts) - 1:
            x1, y1 = pts[i + 1]
            dx, dy = x1 - x, y1 - y
            length = math.hypot(dx, dy)
            if length > 0:
                normals.append((-dy / length, dx / length))

        if normals:
            nx = sum(n[0] for n in normals) / len(normals)
            ny = sum(n[1] for n in normals) / len(normals)
            nlen = math.hypot(nx, ny)
            if nlen:
                nx, ny = nx / nlen, ny / nlen
            else:
                nx, ny = 0.0, 1.0
        else:
            nx, ny = 0.0, 1.0

        b = float(buffer_m)
        left.append((x + nx * b, y + ny * b))
        right.append((x - nx * b, y - ny * b))

    poly_xy = left + list(reversed(right)) + [left[0]]
    return [_xy_to_lonlat(x, y, lat0, lon0) for x, y in poly_xy]


def sample_points_along_line(
    coords_lonlat: list[tuple[float, float]],
    interval_m: float = 200.0,
    include_ends: bool = True,
) -> list[tuple[float, float]]:
    """
    Genera puntos cada cierta distancia sobre una ruta.
    Regresa [(lon, lat), ...].
    """
    if len(coords_lonlat) < 2:
        return coords_lonlat[:]

    interval_m = max(25.0, float(interval_m or 200.0))
    total = polyline_distance_m(coords_lonlat)
    if total <= 0:
        return []

    targets = []
    if include_ends:
        targets.append(0.0)

    d = interval_m
    while d < total:
        targets.append(d)
        d += interval_m

    if include_ends and (not targets or targets[-1] != total):
        targets.append(total)

    out = []
    seg_start_dist = 0.0
    target_idx = 0

    for (lon1, lat1), (lon2, lat2) in zip(coords_lonlat[:-1], coords_lonlat[1:]):
        seg_len = haversine_m(lat1, lon1, lat2, lon2)
        if seg_len <= 0:
            continue

        while target_idx < len(targets) and targets[target_idx] <= seg_start_dist + seg_len:
            tdist = targets[target_idx] - seg_start_dist
            frac = max(0.0, min(1.0, tdist / seg_len))
            lon = lon1 + (lon2 - lon1) * frac
            lat = lat1 + (lat2 - lat1) * frac
            out.append((lon, lat))
            target_idx += 1

        seg_start_dist += seg_len

    return out


def format_distance(distance_m: float) -> str:
    try:
        d = float(distance_m)
    except Exception:
        return "S/D"
    if d >= 1000:
        return f"{d/1000:.2f} km"
    return f"{d:.0f} m"


def format_duration(seconds: float) -> str:
    try:
        s = float(seconds)
    except Exception:
        return "S/D"
    if s <= 0:
        return "S/D"
    minutes = s / 60
    if minutes >= 60:
        return f"{minutes/60:.1f} h"
    return f"{minutes:.0f} min"


# =========================
#   OpenStreetMap / Overpass POI
# =========================
def _route_bbox(coords_lonlat: list[tuple[float, float]], buffer_m: float = 100.0) -> tuple[float, float, float, float]:
    """Regresa bbox Overpass: south, west, north, east."""
    if not coords_lonlat:
        return 0, 0, 0, 0
    lons = [float(c[0]) for c in coords_lonlat]
    lats = [float(c[1]) for c in coords_lonlat]
    lat0 = sum(lats) / len(lats)
    mlat, mlon = _meters_per_degree(lat0)
    dlat = float(buffer_m) / max(1.0, mlat)
    dlon = float(buffer_m) / max(1.0, mlon)
    return max(-90.0, min(lats) - dlat), max(-180.0, min(lons) - dlon), min(90.0, max(lats) + dlat), min(180.0, max(lons) + dlon)


def _point_segment_distance_m(point_lon: float, point_lat: float, a_lon: float, a_lat: float, b_lon: float, b_lat: float) -> float:
    """Distancia aproximada punto-segmento en metros usando proyección local."""
    lat0 = (float(point_lat) + float(a_lat) + float(b_lat)) / 3.0
    lon0 = (float(point_lon) + float(a_lon) + float(b_lon)) / 3.0
    px, py = _lonlat_to_xy(point_lon, point_lat, lat0, lon0)
    ax, ay = _lonlat_to_xy(a_lon, a_lat, lat0, lon0)
    bx, by = _lonlat_to_xy(b_lon, b_lat, lat0, lon0)
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom <= 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    t = max(0.0, min(1.0, t))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy)


def point_to_polyline_distance_m(point_lon: float, point_lat: float, coords_lonlat: list[tuple[float, float]]) -> float:
    if len(coords_lonlat) < 2:
        if len(coords_lonlat) == 1:
            lon, lat = coords_lonlat[0]
            return haversine_m(point_lat, point_lon, lat, lon)
        return float('inf')
    best = float('inf')
    for (a_lon, a_lat), (b_lon, b_lat) in zip(coords_lonlat[:-1], coords_lonlat[1:]):
        d = _point_segment_distance_m(point_lon, point_lat, a_lon, a_lat, b_lon, b_lat)
        if d < best:
            best = d
    return best


def _poi_category(tags: dict) -> str:
    if not tags: return 'POI'
    if tags.get('shop'): return f"Comercio / {tags.get('shop')}"
    amenity = tags.get('amenity')
    if amenity:
        labels = {'fuel':'Gasolinera','restaurant':'Restaurante','fast_food':'Comida rápida','cafe':'Café','bar':'Bar','bank':'Banco','atm':'Cajero','pharmacy':'Farmacia','clinic':'Clínica','hospital':'Hospital','police':'Seguridad pública','bus_station':'Terminal / transporte','parking':'Estacionamiento','marketplace':'Mercado','school':'Escuela','university':'Universidad','college':'Colegio'}
        return labels.get(amenity, f'Servicio / {amenity}')
    if tags.get('tourism'): return f"Turismo / {tags.get('tourism')}"
    if tags.get('office'): return f"Oficina / {tags.get('office')}"
    if tags.get('craft'): return f"Negocio / {tags.get('craft')}"
    if tags.get('industrial'): return f"Empresa / {tags.get('industrial')}"
    if tags.get('man_made'): return f"Instalación / {tags.get('man_made')}"
    return 'POI'


def _is_useful_business_poi(tags: dict) -> bool:
    """Filtra POIs útiles para búsqueda de cámaras. No agrega puntos sin nombre."""
    if not tags: return False
    name = tags.get('name') or tags.get('brand') or tags.get('operator')
    if not name: return False
    bad_amenities = {'bench','toilets','drinking_water','waste_basket','bicycle_parking','parking_space','grave_yard','fountain'}
    if tags.get('amenity') in bad_amenities: return False
    useful = (
        tags.get('shop') or tags.get('office') or tags.get('craft') or tags.get('industrial')
        or tags.get('tourism') in {'hotel','motel','hostel','guest_house','attraction'}
        or tags.get('amenity') in {'fuel','restaurant','fast_food','cafe','bar','bank','atm','pharmacy','clinic','hospital','police','bus_station','parking','marketplace','school','university','college'}
        or tags.get('man_made') in {'works','warehouse'}
    )
    return bool(useful)


def overpass_business_pois_near_route(coords_lonlat: list[tuple[float, float]], buffer_m: float = 100.0, timeout: int = 18, max_results: int = 40) -> list[dict]:
    """Busca negocios/empresas/servicios reales de OSM dentro del corredor. Si no hay resultados, regresa []."""
    if len(coords_lonlat) < 2:
        return []
    south, west, north, east = _route_bbox(coords_lonlat, buffer_m=float(buffer_m) + 30.0)
    if south == north or west == east:
        return []
    bbox = f'{south},{west},{north},{east}'
    query = f"""
    [out:json][timeout:{int(timeout)}];
    (
      node["shop"]({bbox}); way["shop"]({bbox}); relation["shop"]({bbox});
      node["amenity"]({bbox}); way["amenity"]({bbox}); relation["amenity"]({bbox});
      node["tourism"]({bbox}); way["tourism"]({bbox}); relation["tourism"]({bbox});
      node["office"]({bbox}); way["office"]({bbox}); relation["office"]({bbox});
      node["craft"]({bbox}); way["craft"]({bbox}); relation["craft"]({bbox});
      node["industrial"]({bbox}); way["industrial"]({bbox}); relation["industrial"]({bbox});
      node["man_made"]({bbox}); way["man_made"]({bbox}); relation["man_made"]({bbox});
    );
    out center tags {int(max_results) * 4};
    """
    endpoints = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter']
    data = None
    for url in endpoints:
        try:
            r = requests.post(url, data={'data': query}, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            break
        except Exception:
            data = None
    if not data:
        return []
    pois, seen = [], set()
    for el in data.get('elements', []):
        tags = el.get('tags') or {}
        if not _is_useful_business_poi(tags):
            continue
        lat, lon = el.get('lat'), el.get('lon')
        if lat is None or lon is None:
            center = el.get('center') or {}
            lat, lon = center.get('lat'), center.get('lon')
        if lat is None or lon is None:
            continue
        lat, lon = float(lat), float(lon)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        distance = point_to_polyline_distance_m(lon, lat, coords_lonlat)
        if distance > float(buffer_m):
            continue
        key = (el.get('type', 'osm'), el.get('id'))
        if key in seen:
            continue
        seen.add(key)
        name = tags.get('name') or tags.get('brand') or tags.get('operator')
        pois.append({'name': str(name), 'category': _poi_category(tags), 'lat': lat, 'lon': lon, 'distance_m': distance, 'osm_type': key[0], 'osm_id': key[1], 'tags': tags})
    pois.sort(key=lambda x: x.get('distance_m', 999999))
    return pois[:int(max_results)]
