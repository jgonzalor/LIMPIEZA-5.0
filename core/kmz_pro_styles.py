# -*- coding: utf-8 -*-
"""
Estilos KML para Sentinel Mapper KMZ Pro.
"""

from __future__ import annotations


# KML usa formato aabbggrr (alpha, blue, green, red)
COLOR_RED = "ff0000ff"
COLOR_GREEN = "ff00aa00"
COLOR_BLUE = "ffff6600"
COLOR_YELLOW = "ff00ffff"
COLOR_PURPLE = "ffff00aa"
COLOR_GRAY = "ff777777"
COLOR_WHITE = "ffffffff"
COLOR_BLACK = "ff000000"
COLOR_ORANGE = "ff008cff"
COLOR_CYAN = "ffffff00"
COLOR_LIME = "ff00ff00"

POLY_BLUE_TRANSPARENT = "330066ff"
POLY_GRAY_TRANSPARENT = "22000000"
POLY_GREEN_TRANSPARENT = "3300aa00"
POLY_RED_TRANSPARENT = "330000ff"
POLY_YELLOW_TRANSPARENT = "3300ffff"
POLY_CYAN_TRANSPARENT = "33ffff00"
POLY_LIME_TRANSPARENT = "3300ff00"


ICON_URLS = {
    "antenna": "http://maps.google.com/mapfiles/kml/shapes/target.png",
    "event": "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png",
    "phone": "http://maps.google.com/mapfiles/kml/shapes/phone.png",
    "route": "http://maps.google.com/mapfiles/kml/shapes/track.png",
    "star": "http://maps.google.com/mapfiles/kml/shapes/star.png",
    "info": "http://maps.google.com/mapfiles/kml/shapes/info-i.png",
}


EVENT_STYLE = {
    "VOZ ENTRANTE": {
        "color": COLOR_GREEN,
        "poly": POLY_GREEN_TRANSPARENT,
        "icon": ICON_URLS["phone"],
        "label": "Voz entrante",
    },
    "VOZ SALIENTE": {
        "color": COLOR_RED,
        "poly": POLY_RED_TRANSPARENT,
        "icon": ICON_URLS["phone"],
        "label": "Voz saliente",
    },
    "DATOS": {
        "color": COLOR_BLUE,
        "poly": POLY_BLUE_TRANSPARENT,
        "icon": ICON_URLS["event"],
        "label": "Datos",
    },
    "SMS": {
        "color": COLOR_YELLOW,
        "poly": POLY_YELLOW_TRANSPARENT,
        "icon": ICON_URLS["event"],
        "label": "SMS",
    },
    "TRANSFER": {
        "color": COLOR_ORANGE,
        "poly": POLY_YELLOW_TRANSPARENT,
        "icon": ICON_URLS["event"],
        "label": "Transfer",
    },
    "SIN TIPO": {
        "color": COLOR_GRAY,
        "poly": POLY_GRAY_TRANSPARENT,
        "icon": ICON_URLS["event"],
        "label": "Sin tipo",
    },
}


def get_event_style(tipo: str) -> dict:
    return EVENT_STYLE.get(str(tipo or "").upper(), {
        "color": COLOR_PURPLE,
        "poly": POLY_GRAY_TRANSPARENT,
        "icon": ICON_URLS["event"],
        "label": str(tipo or "Otro"),
    })


def apply_icon_style(pnt, color: str, icon_href: str, scale: float = 1.0, label_scale: float = 0.75):
    pnt.style.iconstyle.icon.href = icon_href
    pnt.style.iconstyle.color = color
    pnt.style.iconstyle.scale = scale
    pnt.style.labelstyle.scale = label_scale
    return pnt


def apply_line_style(line, color: str, width: int = 3):
    line.style.linestyle.color = color
    line.style.linestyle.width = width
    return line


def apply_polygon_style(poly, line_color: str, poly_color: str, line_width: int = 1):
    poly.style.linestyle.color = line_color
    poly.style.linestyle.width = line_width
    poly.style.polystyle.color = poly_color
    return poly
