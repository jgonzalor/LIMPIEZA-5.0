# core/agent_intents_registry.py
from __future__ import annotations

from typing import Dict, Any

from core.agent_intents import (
    intent_top_contactos_por_eventos,
    intent_top_ubicaciones_por_eventos,
    intent_ultimos_eventos,
    intent_llamadas_entrantes,
    intent_llamadas_salientes,
)

INTENTS: Dict[str, Dict[str, Any]] = {
    "top_contactos_por_eventos": {
        "label": "Top contactos por eventos",
        "handler": intent_top_contactos_por_eventos,
        "requires_geo": False,
    },
    "top_ubicaciones_por_eventos": {
        "label": "Top ubicaciones (LAT/LON) por eventos",
        "handler": intent_top_ubicaciones_por_eventos,
        "requires_geo": True,
    },
    "ultimos_eventos": {
        "label": "Últimos eventos / últimas llamadas",
        "handler": intent_ultimos_eventos,
        "requires_geo": False,
    },
    "llamadas_entrantes": {
        "label": "Detalle: llamadas entrantes",
        "handler": intent_llamadas_entrantes,
        "requires_geo": False,
    },
    "llamadas_salientes": {
        "label": "Detalle: llamadas salientes",
        "handler": intent_llamadas_salientes,
        "requires_geo": False,
    },
}
