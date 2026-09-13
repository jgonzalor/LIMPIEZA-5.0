# core/agent_orchestrator.py
# Orquestador: pregunta -> intent -> handler -> respuesta + evidencia + filtros
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from core.agent_intents_registry import INTENTS


# Keywords
LOCATION_KW = [
    "ubicacion", "ubicación", "coordenada", "coordenadas",
    "lat", "latitud", "lon", "longitud", "gps",
    "lugar", "punto",
]

CONTACT_KW = [
    "contacto", "contactos", "contraparte",
    "con quien", "quien le llama", "quien le marco", "quien le marcó",
]

RECENT_KW = ["ultima", "última", "ultimas", "últimas", "ultimo", "último", "reciente", "recientes", "ultimos", "últimos"]
CALL_KW = ["llamada", "llamadas", "voz", "call", "calls"]
IN_KW = ["entrante", "entrantes", "recibida", "recibidas", "incoming", "inbound"]
OUT_KW = ["saliente", "salientes", "realizada", "realizadas", "outgoing", "outbound"]
ALL_KW = ["todas", "todo", "completo", "enteras", "todas las"]
FIRST_KW = ["primer", "primera", "primero", "primeras", "primeros", "inicial", "inicio", "mas antigua", "más antigua", "antigua", "antiguas"]


def _norm(s: str) -> str:
    return (s or "").strip().lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")


def _extract_top_n(q: str, default: int = 10) -> int:
    """
    Extrae N desde:
    - "top 20"
    - "ultimas 20 llamadas" / "últimos 15"
    - "primeras 20 llamadas" / "20 primeras llamadas"
    - "20 recientes"
    - "dame 30"
    - si dice "todas" => 5000 (tope de seguridad para UI)
    - si dice "primera/primer" y NO hay número => 1
    """
    qn = _norm(q)

    # Si hay número explícito, lo tomamos primero
    patterns = [
        r"\btop\s*(\d{1,4})\b",
        r"\bultim[ao]s?\s*(\d{1,4})\b",
        r"\b(\d{1,4})\s*ultim[ao]s?\b",
        r"\bprimer[ao]s?\s*(\d{1,4})\b",         # primeras 20
        r"\b(\d{1,4})\s*primer[ao]s?\b",         # 20 primeras
        r"\brecientes?\s*(\d{1,4})\b",
        r"\b(\d{1,4})\s*recientes?\b",
        r"\bdame\s*(\d{1,4})\b",
        r"\b(\d{1,4})\s*(mas|más)\b",
    ]
    for pat in patterns:
        m = re.search(pat, qn)
        if m:
            n = int(m.group(1))
            return max(1, min(n, 5000))

    # Si pide "primera" sin número => 1
    if any(k in qn for k in FIRST_KW):
        return 1

    # Si pide "todas" sin número => 5000
    if any(k in qn for k in ALL_KW):
        return 5000

    return default


def classify_intent(question: str) -> str:
    q = _norm(question)

    # ✅ llamadas entrantes / salientes (detalle)
    if any(k in q for k in CALL_KW) and any(k in q for k in IN_KW):
        return "llamadas_entrantes"
    if any(k in q for k in CALL_KW) and any(k in q for k in OUT_KW):
        return "llamadas_salientes"

    # ✅ últimos eventos / últimas llamadas (si no especifica dirección)
    if any(k in q for k in RECENT_KW) and any(k in q for k in CALL_KW):
        return "ultimos_eventos"

    # ✅ ubicación
    if any(k in q for k in LOCATION_KW):
        return "top_ubicaciones_por_eventos"

    # ✅ contactos
    if any(k in q for k in CONTACT_KW):
        return "top_contactos_por_eventos"

    # fallback
    return "top_contactos_por_eventos"


def run_question(
    con,
    df_cols,
    question: str,
    forced_intent: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    q = question or ""
    top_n = _extract_top_n(q, default=10)

    intent = forced_intent if forced_intent and forced_intent != "(auto)" else classify_intent(q)

    if intent not in INTENTS:
        return {
            "intent": intent,
            "answer": "No reconozco ese intent. Revisa el registro de intents.",
            "evidence": None,
            "applied_filters": filters or {},
        }

    handler = INTENTS[intent]["handler"]

    # ✅ pasamos 'question' a handlers que lo necesiten (primera/últimas/entrantes/salientes)
    try:
        out = handler(con, df_cols, filters=filters or {}, top_n=top_n, question=q)
    except TypeError:
        out = handler(con, df_cols, filters=filters or {}, top_n=top_n)

    out["intent"] = intent
    return out
