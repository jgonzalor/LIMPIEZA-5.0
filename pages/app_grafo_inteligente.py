"""Sentinel 5.2.0: editor visual de actores, vínculos y fichas con fotografía.

La página es deliberadamente autocontenida para que la evolución del módulo no
toque guardian, navegación, limpieza ni los demás módulos estables de Go Mapper.
Los datos observados, las relaciones manuales y las inferencias quedan separados
por ``source_type`` y nunca se atribuye parentesco automáticamente.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from html import escape
from io import BytesIO
import base64
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import unicodedata
import uuid
import zlib
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Go Mapper · Mapa investigativo", page_icon="🧭", layout="wide")

from guardian import login_guard
from suite_nav import render_suite_sidebar
from ui.components import render_info_panel, render_kpi_row, render_page_header, render_section


APP_VERSION = "5.2.0-editor-visual"
LOCAL_TZ = "America/Mazatlan"
VALID_EVENT_TYPES = (
    "DATOS", "DATOS WIFI", "VOZ ENTRANTE", "VOZ SALIENTE", "VOZ TRANSITO",
    "VOZ TRANSFER", "MENSAJE ENTRANTE", "MENSAJE SALIENTE",
)
CONFIDENCE_LEVELS = ("CONFIRMADO", "PROBABLE", "INFERIDO", "PENDIENTE", "DESCARTADO")
SOURCE_TYPES = ("IMPORTADO", "MANUAL", "INFERIDO", "DESCARTADO")
MANUAL_SOURCES = (
    "Entrevista", "Informe policial", "Informe pericial", "Documento oficial", "Acta",
    "Fotografía", "Red social", "Observación de campo", "Declaración", "Captura manual",
    "Oficio", "Otra fuente documentada",
)
PERSONAL_RELATIONS = (
    "PADRE_DE", "MADRE_DE", "HIJO_DE", "HIJA_DE", "HERMANO_DE", "HERMANA_DE",
    "ABUELO_DE", "ABUELA_DE", "NIETO_DE", "NIETA_DE", "TIO_DE", "TIA_DE",
    "SOBRINO_DE", "SOBRINA_DE", "PRIMO_DE", "PRIMA_DE", "PAREJA_DE", "CONYUGE_DE",
    "EX_PAREJA_DE", "FAMILIAR_DE", "AMIGO_DE", "SOCIO_DE", "CONOCIDO_DE", "RELACION_PERSONAL_OTRA",
)
HIERARCHY_RELATIONS = ("DIRIGE_A", "SUPERVISA_A", "COORDINA_A", "REPORTA_A", "SUBORDINADO_DE")
# Stored source → target is preserved; these two relations point up the hierarchy.
UPWARD_RELATIONS = {"REPORTA_A", "SUBORDINADO_DE"}
RELATION_TYPES = (
    "UTILIZA", "ASOCIADO_A", "TIENE_PERFIL", "PROPIETARIO_DE", "RESIDE_EN",
    "TRABAJA_EN", "UBICADO_EN", "UTILIZA_ANTENA", "COMUNICACION",
    *PERSONAL_RELATIONS, *HIERARCHY_RELATIONS, "RELACION_DOCUMENTAL",
)
ENTITY_TYPES = (
    "PERSONA", "TELEFONO", "IMEI", "IMSI/SIM", "PERFIL DIGITAL", "CORREO ELECTRONICO", "VEHICULO",
    "DOMICILIO", "EMPRESA", "ANTENA", "UBICACION", "EVIDENCIA", "EVENTO", "CASO",
)
ENTITY_ICONS = {
    "PERSONA": "👤", "TELEFONO": "📱", "IMEI": "📟", "IMSI/SIM": "💳",
    "PERFIL DIGITAL": "🌐", "CORREO ELECTRONICO": "✉️", "VEHICULO": "🚗", "DOMICILIO": "🏠", "EMPRESA": "🏢",
    "ANTENA": "📡", "UBICACION": "📍", "EVIDENCIA": "📄", "EVENTO": "🕒", "CASO": "🗂️",
}
ENTITY_COLORS = {
    "PERSONA": "#e46d72", "TELEFONO": "#4f8ef7", "IMEI": "#7b61ff", "IMSI/SIM": "#9b59b6",
    "PERFIL DIGITAL": "#00a896", "CORREO ELECTRONICO": "#0ea5e9", "VEHICULO": "#f39c35", "DOMICILIO": "#e67e22",
    "EMPRESA": "#2f9e72", "ANTENA": "#0891b2", "UBICACION": "#14b8a6", "EVIDENCIA": "#6b7280",
    "EVENTO": "#64748b", "CASO": "#0f3d62",
}
ENTITY_COLUMNS = [
    "entity_id", "entity_type", "label", "normalized", "source_type", "source_detail",
    "created_by", "created_at", "confidence", "notes", "evidence_ids", "metadata",
]
RELATION_COLUMNS = [
    "relation_id", "source_id", "target_id", "relation_type", "start_date", "end_date",
    "source", "description", "confidence", "source_type", "source_detail", "created_by",
    "created_at", "notes", "evidence_ids", "status", "support_count", "visual_color",
]
EVENT_COLUMNS = [
    "event_id", "logical_event_id", "event_type", "event_type_raw", "classification_reason",
    "source_id", "target_id", "datetime", "duration_seconds", "imei", "imsi", "antenna",
    "latitude", "longitude", "plus_code", "address", "azimuth", "import_id", "file_name", "sheet_name", "row_number", "source_hash",
    "source_type", "evidence_id", "dedup_tolerance_seconds", "status",
]
SUPPORT_COLUMNS = [
    "support_id", "logical_event_id", "event_id", "import_id", "file_name", "sheet_name",
    "row_number", "source_hash", "source_type", "evidence_id", "raw_json", "classification_reason", "event_type",
]
EVIDENCE_COLUMNS = [
    "evidence_id", "evidence_type", "title", "source", "file_name", "sheet_name", "row_number",
    "source_hash", "captured_at", "created_by", "description", "raw_json",
]


def empty_df(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def now_local() -> str:
    return datetime.now(ZoneInfo(LOCAL_TZ)).isoformat(timespec="seconds")


def user_name() -> str:
    return str(st.session_state.get("username") or st.session_state.get("user_name") or "usuario_local")


def text_value(value: object, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def norm_text(value: object) -> str:
    raw = text_value(value).upper()
    return "".join(ch for ch in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(ch))


def normalize_number(value: object) -> str:
    raw = text_value(value)
    if not raw:
        return ""
    if re.fullmatch(r"[+]?\d+[.]0+", raw):
        raw = raw.split(".", 1)[0]
    plus = "+" if raw.startswith("+") else ""
    digits = re.sub(r"\D", "", raw)
    return plus + digits if digits else ""


def normalize_identifier(value: object) -> str:
    return re.sub(r"[^A-Z0-9+]+", "", norm_text(value))


def parse_datetime_value(value: object) -> str:
    if value is None or text_value(value) == "":
        return ""
    parsed = None
    if isinstance(value, (datetime, pd.Timestamp)):
        parsed = pd.Timestamp(value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        if 20000 <= float(value) <= 80000:
            parsed = pd.Timestamp("1899-12-30") + pd.to_timedelta(float(value), unit="D")
    if parsed is None:
        parsed = pd.to_datetime(text_value(value), errors="coerce", dayfirst=True)
    if parsed is None or pd.isna(parsed):
        return ""
    parsed = pd.Timestamp(parsed)
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert(LOCAL_TZ)
    return parsed.isoformat(timespec="seconds")


def parse_duration(value: object) -> int:
    raw = text_value(value)
    if not raw:
        return 0
    if ":" in raw:
        parts = raw.split(":")
        try:
            nums = [float(p.replace(",", ".")) for p in parts]
            if len(nums) == 3:
                return max(0, int(nums[0] * 3600 + nums[1] * 60 + nums[2]))
            if len(nums) == 2:
                return max(0, int(nums[0] * 60 + nums[1]))
        except ValueError:
            pass
    try:
        return max(0, int(float(raw.replace(",", "."))))
    except ValueError:
        return 0


def parse_coordinate(value: object) -> float | None:
    raw = text_value(value).replace(",", ".")
    if not raw:
        return None
    try:
        number = float(re.sub(r"[^0-9+\-.]", "", raw))
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def short_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def find_column(columns: list[str], candidates: tuple[str, ...], fallback: str = "") -> str:
    normalized = {norm_text(c): c for c in columns}
    for candidate in candidates:
        if norm_text(candidate) in normalized:
            return normalized[norm_text(candidate)]
    for col in columns:
        if any(norm_text(candidate) in norm_text(col) for candidate in candidates):
            return col
    return fallback


def event_type(raw_type: object, direction: object = "") -> tuple[str, str]:
    raw, direct = norm_text(raw_type), norm_text(direction)
    if not raw:
        return "NO_CLASIFICADO", "Tipo vacío; se conserva como soporte sin relación operativa."
    valid_norm = {norm_text(x): x for x in VALID_EVENT_TYPES}
    if raw in valid_norm:
        return valid_norm[raw], "Tipo válido del catálogo CDR."
    if any(token in raw for token in ("ADMIN", "TIPO", "PREPAGO", "NAN", "UNKNOWN", "DESCONOC")):
        return "NO_CLASIFICADO", "Tipo administrativo o no reconocido; no crea comunicación."
    if "WIFI" in raw:
        return "DATOS WIFI", "Clasificación por palabra WIFI."
    if any(token in raw for token in ("DATOS", "DATA", "GPRS", "INTERNET", "LTE")):
        return "DATOS", "Clasificación por tráfico de datos; se conserva como evento."
    if any(token in raw for token in ("SMS", "MENSAJE", "MESSAGE")):
        return ("MENSAJE ENTRANTE" if any(x in direct for x in ("ENTR", "IN")) else "MENSAJE SALIENTE"), "Clasificación por mensaje y dirección."
    if any(token in raw for token in ("VOZ", "VOICE", "LLAM", "CALL")):
        if "TRANSITO" in direct or "TRÁNSITO" in direct:
            return "VOZ TRANSITO", "Clasificación por dirección tránsito."
        if "TRANSFER" in direct or "TRANSFERENCIA" in direct:
            return "VOZ TRANSFER", "Clasificación por dirección transferencia."
        return ("VOZ ENTRANTE" if any(x in direct for x in ("ENTR", "IN")) else "VOZ SALIENTE"), "Clasificación por voz y dirección."
    return "NO_CLASIFICADO", "Tipo fuera del catálogo; se conserva la fila y su procedencia."


def entity_id(entity_type: str, value: object) -> str:
    prefix = re.sub(r"[^A-Z0-9]+", "_", norm_text(entity_type)).strip("_")[:12] or "ENT"
    key = normalize_identifier(value) or uuid.uuid4().hex[:8].upper()
    return f"{prefix}:{key}"


def add_entity(state: dict, entity_type: str, label: object, *, source_type: str = "IMPORTADO",
               source_detail: str = "", confidence: str = "CONFIRMADO", notes: str = "",
               evidence_ids: list[str] | None = None, metadata: dict | None = None) -> str:
    display = text_value(label, "Sin etiqueta")
    normalized = normalize_identifier(display) or norm_text(display)
    # A matching name is not proof of identity. People always receive their own ID.
    existing = None if entity_type == "PERSONA" else next((x for x in state["entities"] if x["entity_type"] == entity_type and x["normalized"] == normalized), None)
    if existing:
        if evidence_ids:
            prior = text_value(existing.get("evidence_ids")).split(",")
            existing["evidence_ids"] = ",".join(sorted(set(filter(None, prior + evidence_ids))))
        return existing["entity_id"]
    record = {
        "entity_id": short_id("PERSONA") if entity_type == "PERSONA" else entity_id(entity_type, display), "entity_type": entity_type, "label": display,
        "normalized": normalized, "source_type": source_type, "source_detail": source_detail,
        "created_by": user_name(), "created_at": now_local(), "confidence": confidence,
        "notes": notes, "evidence_ids": ",".join(evidence_ids or []), "metadata": json.dumps(metadata or {}, ensure_ascii=False),
    }
    state["entities"].append(record)
    return record["entity_id"]


def make_relation(state: dict, source_id: str, target_id: str, relation_type: str, *, source: str = "",
                  description: str = "", confidence: str = "CONFIRMADO", source_type: str = "IMPORTADO",
                  source_detail: str = "", start_date: str = "", end_date: str = "", notes: str = "",
                  evidence_ids: list[str] | None = None, status: str = "ACTIVA", support_count: int = 0) -> str:
    if not source_id or not target_id or source_id == target_id:
        return ""
    if confidence == "DESCARTADO" and status == "ACTIVA":
        status = "DESCARTADA"
    rid = short_id("REL")
    state["relationships"].append({
        "relation_id": rid, "source_id": source_id, "target_id": target_id, "relation_type": relation_type,
        "start_date": start_date, "end_date": end_date, "source": source, "description": description,
        "confidence": confidence, "source_type": source_type, "source_detail": source_detail,
        "created_by": user_name(), "created_at": now_local(), "notes": notes,
        "evidence_ids": ",".join(evidence_ids or []), "status": status, "support_count": int(support_count or 0),
    })
    return rid


def append_audit(state: dict, action: str, detail: str, *, object_id: str = "") -> None:
    state["audit"].append({
        "audit_id": short_id("AUD"), "timestamp": now_local(), "user": user_name(),
        "action": action, "object_id": object_id, "detail": detail,
    })


def new_state(case_name: str = "Caso sin nombre", case_id: str = "") -> dict:
    return {
        "case_id": case_id or short_id("CASO"), "case_name": case_name, "created_at": now_local(),
        "entities": [], "relationships": [], "events": [], "support": [], "evidences": [],
        "audit": [], "imports": [], "targets": [], "dedup_tolerance": 30,
        "assets": {}, "entity_history": [], "canvas_revision": 0, "canvas_positions": {}, "canvas_sizes": {},
    }


def frame_from_records(records: list[dict], columns: list[str]) -> pd.DataFrame:
    if not records:
        return empty_df(columns)
    frame = pd.DataFrame(records)
    for col in columns:
        if col not in frame:
            frame[col] = ""
    return frame[columns].fillna("")


def state_frames(state: dict) -> dict[str, pd.DataFrame]:
    return {
        "ENTIDADES": frame_from_records(state.get("entities", []), ENTITY_COLUMNS),
        "RELACIONES": frame_from_records(state.get("relationships", []), RELATION_COLUMNS),
        "EVENTOS": frame_from_records(state.get("events", []), EVENT_COLUMNS),
        "SOPORTE_CDR": frame_from_records(state.get("support", []), SUPPORT_COLUMNS),
        "EVIDENCIAS": frame_from_records(state.get("evidences", []), EVIDENCE_COLUMNS),
        "AUDITORIA": frame_from_records(state.get("audit", []), ["audit_id", "timestamp", "user", "action", "object_id", "detail"]),
    }


def read_upload(upload) -> tuple[pd.DataFrame, str, str, str]:
    """Read one upload, prioritizing Datos_Limpios and excluding Duplicados."""
    payload = upload.getvalue() if hasattr(upload, "getvalue") else bytes(upload)
    name = text_value(getattr(upload, "name", "CDR"), "CDR")
    digest = file_hash(payload)
    if name.lower().endswith(".csv"):
        frame = pd.read_csv(BytesIO(payload), dtype=str, keep_default_na=False)
        return frame.fillna(""), "CSV", digest, name
    if name.lower().endswith((".xlsx", ".xls", ".xlsm")):
        book = pd.ExcelFile(BytesIO(payload))
        sheets = list(book.sheet_names)
        excluded = {"DUPLICADOS", "LOG", "ESTADISTICAS", "ESTADISTICA"}
        clean = next((s for s in sheets if norm_text(s) == "DATOS_LIMPIOS"), None)
        eligible = [s for s in sheets if norm_text(s) not in excluded]
        if not clean and not eligible:
            raise ValueError("El libro solo contiene hojas excluidas (Duplicados/LOG/ESTADISTICAS).")
        selected = clean or eligible[0]
        frame = pd.read_excel(book, sheet_name=selected, dtype=str, keep_default_na=False)
        return frame.fillna(""), selected, digest, name
    raise ValueError("Formato no compatible; utiliza Excel o CSV.")


def infer_mapping(frame: pd.DataFrame) -> dict[str, str]:
    cols = [text_value(c) for c in frame.columns]
    mapping = {
        "source": find_column(cols, ("Número A", "Numero A", "Origen", "A", "MSISDN A", "Calling"), cols[0] if cols else ""),
        "target": find_column(cols, ("Número B", "Numero B", "Destino", "B", "MSISDN B", "Called"), cols[1] if len(cols) > 1 else (cols[0] if cols else "")),
        "type": find_column(cols, ("Tipo de evento", "Tipo", "Evento", "Call Type", "Service"), ""),
        "direction": find_column(cols, ("Dirección", "Direccion", "Sentido", "Direction"), ""),
        "datetime": find_column(cols, ("Fecha/Hora", "Fecha Hora", "Datetime", "Timestamp", "Inicio", "Fecha"), ""),
        "time": find_column(cols, ("Hora", "Time"), ""),
        "duration": find_column(cols, ("Duración", "Duracion", "Segundos", "Duration"), ""),
        "imei": find_column(cols, ("IMEI",), ""),
        "imsi": find_column(cols, ("IMSI", "SIM", "ICCID"), ""),
        "antenna": find_column(cols, ("Antena", "Cell ID", "Celda", "Torre"), ""),
        "latitude": find_column(cols, ("Latitud", "Latitude", "LAT"), ""),
        "longitude": find_column(cols, ("Longitud", "Longitude", "LON", "LNG"), ""),
        "plus_code": find_column(cols, ("Plus Code", "PlusCode", "PLUSCODE"), ""),
        "address": find_column(cols, ("Dirección", "Direccion", "Address", "Domicilio"), ""),
        "azimuth": find_column(cols, ("Azimuth", "Azimut", "Bearing"), ""),
        "location": find_column(cols, ("Ubicación", "Ubicacion", "Domicilio", "Lugar"), ""),
    }
    # Avoid matching a combined Fecha/Hora column as both datetime and time,
    # and avoid treating a postal address as a call direction.
    if mapping.get("time") == mapping.get("datetime"):
        mapping["time"] = ""
    if mapping.get("direction") == mapping.get("address"):
        mapping["direction"] = ""
    return mapping


def _cell(row: pd.Series, column: str) -> str:
    return text_value(row.get(column, "")) if column else ""


def classify_rows(frame: pd.DataFrame, mapping: dict[str, str], *, import_id: str,
                  file_name: str, sheet_name: str, source_hash: str, captured_at: str | None = None) -> tuple[list[dict], list[dict]]:
    """Normalize every source row while retaining the raw row for audit/support."""
    captured_at = captured_at or now_local()
    rows, evidences = [], []
    for offset, (_, row) in enumerate(frame.iterrows(), start=2):
        raw = {text_value(k): text_value(v) for k, v in row.to_dict().items()}
        evidence_id = short_id("EVD")
        raw_type, direction = _cell(row, mapping.get("type", "")), _cell(row, mapping.get("direction", ""))
        canonical, reason = event_type(raw_type, direction)
        source = normalize_number(_cell(row, mapping.get("source", ""))) or normalize_identifier(_cell(row, mapping.get("source", "")))
        target = normalize_number(_cell(row, mapping.get("target", ""))) or normalize_identifier(_cell(row, mapping.get("target", "")))
        dt = _cell(row, mapping.get("datetime", ""))
        if not dt and mapping.get("date"):
            dt = _cell(row, mapping["date"])
        if mapping.get("time") and dt and _cell(row, mapping["time"]):
            dt = f"{dt} {_cell(row, mapping['time'])}"
        latitude, longitude = parse_coordinate(_cell(row, mapping.get("latitude", ""))), parse_coordinate(_cell(row, mapping.get("longitude", "")))
        rec = {
            "source_raw": _cell(row, mapping.get("source", "")), "target_raw": _cell(row, mapping.get("target", "")),
            "source": source, "target": target, "event_type_raw": raw_type, "direction": direction,
            "event_type": canonical, "classification_reason": reason, "datetime": parse_datetime_value(dt),
            "duration_seconds": parse_duration(_cell(row, mapping.get("duration", ""))),
            "imei": normalize_identifier(_cell(row, mapping.get("imei", ""))), "imsi": normalize_identifier(_cell(row, mapping.get("imsi", ""))),
            "antenna": _cell(row, mapping.get("antenna", "")), "latitude": latitude if latitude is not None else "",
            "longitude": longitude if longitude is not None else "", "plus_code": _cell(row, mapping.get("plus_code", "")),
            "address": _cell(row, mapping.get("address", "")), "azimuth": _cell(row, mapping.get("azimuth", "")),
            "import_id": import_id, "file_name": file_name,
            "sheet_name": sheet_name, "row_number": offset, "source_hash": source_hash, "evidence_id": evidence_id,
            "source_type": "IMPORTADO", "raw_json": json.dumps(raw, ensure_ascii=False, default=str),
        }
        rows.append(rec)
        evidences.append({
            "evidence_id": evidence_id, "evidence_type": "CDR_ROW", "title": f"{file_name} · fila {offset}",
            "source": "CDR", "file_name": file_name, "sheet_name": sheet_name, "row_number": offset,
            "source_hash": source_hash, "captured_at": captured_at, "created_by": user_name(),
            "description": reason, "raw_json": rec["raw_json"],
        })
    return rows, evidences


def _event_datetime(row: dict) -> datetime | None:
    raw = text_value(row.get("datetime"))
    if not raw:
        return None
    try:
        return pd.Timestamp(raw).to_pydatetime()
    except (TypeError, ValueError):
        return None


def deduplicate_rows(rows: list[dict], tolerance: int = 30) -> tuple[list[dict], list[dict]]:
    """Greedy logical-event grouping; every source row remains in support."""
    groups: list[dict] = []
    support: list[dict] = []
    for row in rows:
        source, target = row.get("source", ""), row.get("target", "")
        raw_dt = _event_datetime(row)
        key = (source, target, row.get("event_type", "NO_CLASIFICADO"), int(row.get("duration_seconds") or 0))
        chosen = None
        if raw_dt is not None:
            for candidate in reversed(groups):
                if candidate["key"] != key or candidate["datetime"] is None:
                    continue
                if abs((raw_dt - candidate["datetime"]).total_seconds()) <= tolerance:
                    chosen = candidate
                    break
        if chosen is None:
            chosen = {"key": key, "datetime": raw_dt, "rows": [], "logical_event_id": short_id("LEVT")}
            groups.append(chosen)
        chosen["rows"].append(row)
        support.append({
            "support_id": short_id("SUP"), "logical_event_id": chosen["logical_event_id"], "event_id": "",
            "import_id": row.get("import_id", ""), "file_name": row.get("file_name", ""), "sheet_name": row.get("sheet_name", ""),
            "row_number": row.get("row_number", ""), "source_hash": row.get("source_hash", ""), "source_type": "IMPORTADO",
            "evidence_id": row.get("evidence_id", ""), "raw_json": row.get("raw_json", ""), "classification_reason": row.get("classification_reason", ""),
            "event_type": row.get("event_type", "NO_CLASIFICADO"),
        })
    logical_events: list[dict] = []
    for group in groups:
        first = group["rows"][0]
        event_id = short_id("EVT")
        for item in support:
            if item["logical_event_id"] == group["logical_event_id"]:
                item["event_id"] = event_id
        logical_events.append({
            "event_id": event_id, "logical_event_id": group["logical_event_id"],
            "event_type": first.get("event_type", "NO_CLASIFICADO"), "event_type_raw": first.get("event_type_raw", ""),
            "classification_reason": first.get("classification_reason", ""), "source_id": first.get("source", ""),
            "target_id": first.get("target", ""), "datetime": first.get("datetime", ""),
            "duration_seconds": int(first.get("duration_seconds") or 0), "imei": first.get("imei", ""),
            "imsi": first.get("imsi", ""), "antenna": first.get("antenna", ""), "latitude": first.get("latitude", ""),
            "longitude": first.get("longitude", ""), "plus_code": first.get("plus_code", ""),
            "address": first.get("address", ""), "azimuth": first.get("azimuth", ""), "import_id": first.get("import_id", ""),
            "file_name": first.get("file_name", ""), "sheet_name": first.get("sheet_name", ""),
            "row_number": first.get("row_number", ""), "source_hash": first.get("source_hash", ""),
            "source_type": "IMPORTADO", "evidence_id": first.get("evidence_id", ""),
            "dedup_tolerance_seconds": tolerance, "status": "NO_CLASIFICADO" if first.get("event_type") == "NO_CLASIFICADO" else "ACTIVO",
        })
    return logical_events, support


def _add_import_evidence(state: dict, profile: dict) -> None:
    state["imports"].append({
        "import_id": profile["import_id"], "file_name": profile["file_name"], "sheet_name": profile["sheet_name"],
        "source_hash": profile["source_hash"], "rows": len(profile["frame"]), "captured_at": profile.get("captured_at", now_local()),
    })
    append_audit(state, "IMPORTAR_CDR", f"{profile['file_name']} · hoja {profile['sheet_name']} · {len(profile['frame'])} filas", object_id=profile["import_id"])


def build_state(profiles: list[dict], configs: list[dict], *, tolerance: int = 30,
                case_id: str = "", case_name: str = "Caso sin nombre", target_labels: list[str] | None = None,
                manual_persons: list[str] | None = None) -> dict:
    state = new_state(case_name, case_id)
    state["dedup_tolerance"] = tolerance
    all_rows, all_evidence = [], []
    for profile, mapping in zip(profiles, configs):
        _add_import_evidence(state, profile)
        rows, evidence = classify_rows(profile["frame"], mapping, import_id=profile["import_id"], file_name=profile["file_name"], sheet_name=profile["sheet_name"], source_hash=profile["source_hash"])
        all_rows.extend(rows)
        all_evidence.extend(evidence)
    events, support = deduplicate_rows(all_rows, tolerance)
    state["events"], state["support"], state["evidences"] = events, support, all_evidence
    target_norm = {normalize_number(x) or normalize_identifier(x) for x in (target_labels or []) if text_value(x)}
    phone_ids: dict[str, str] = {}
    # Administrative/unknown rows stay in EVENTS/SOPORTE only; they do not create
    # operational entities or relationships.
    operational_rows = [row for row in all_rows if row.get("event_type") in VALID_EVENT_TYPES]
    for row in operational_rows:
        for number in (row.get("source"), row.get("target")):
            if number:
                phone_ids[number] = add_entity(state, "TELEFONO", number, source_detail=f"CDR · {row.get('file_name', '')}", evidence_ids=[row.get("evidence_id", "")])
        if row.get("imei"):
            imei_id = add_entity(state, "IMEI", row["imei"], source_detail=row.get("file_name", ""), evidence_ids=[row.get("evidence_id", "")])
            if row.get("source") in phone_ids:
                make_relation(state, phone_ids[row["source"]], imei_id, "ASOCIADO_A", source="CDR", source_type="IMPORTADO", description="IMEI observado en la fila CDR.", evidence_ids=[row.get("evidence_id", "")])
        if row.get("imsi"):
            imsi_id = add_entity(state, "IMSI/SIM", row["imsi"], source_detail=row.get("file_name", ""), evidence_ids=[row.get("evidence_id", "")])
            if row.get("source") in phone_ids:
                make_relation(state, phone_ids[row["source"]], imsi_id, "ASOCIADO_A", source="CDR", source_type="IMPORTADO", description="IMSI/SIM observado en la fila CDR.", evidence_ids=[row.get("evidence_id", "")])
        if row.get("antenna"):
            ant_id = add_entity(state, "ANTENA", row["antenna"], source_detail=row.get("file_name", ""), evidence_ids=[row.get("evidence_id", "")])
            if row.get("source") in phone_ids:
                make_relation(state, phone_ids[row["source"]], ant_id, "UTILIZA_ANTENA", source="CDR", source_type="IMPORTADO", evidence_ids=[row.get("evidence_id", "")])
        if row.get("latitude") != "" and row.get("longitude") != "":
            location = f"{row['latitude']},{row['longitude']}"
            loc_id = add_entity(state, "UBICACION", location, source_detail=row.get("file_name", ""), evidence_ids=[row.get("evidence_id", "")], metadata={"latitude": row["latitude"], "longitude": row["longitude"]})
            if row.get("source") in phone_ids:
                make_relation(state, phone_ids[row["source"]], loc_id, "UBICADO_EN", source="CDR", source_type="IMPORTADO", evidence_ids=[row.get("evidence_id", "")])
    # Communication aggregates are based only on catalogued event types.
    pair_evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
    pair_count: Counter[tuple[str, str]] = Counter()
    evidence_by_logical = defaultdict(list)
    for item in support:
        if item.get("evidence_id"):
            evidence_by_logical[item.get("logical_event_id")].append(item.get("evidence_id"))
    for event in events:
        if event["event_type"] not in VALID_EVENT_TYPES or not event["source_id"] or not event["target_id"]:
            continue
        src, dst = phone_ids.get(event["source_id"], ""), phone_ids.get(event["target_id"], "")
        if not src or not dst:
            continue
        key = (src, dst)
        pair_count[key] += 1
        pair_evidence[key].extend(evidence_by_logical.get(event.get("logical_event_id"), [event.get("evidence_id", "")]))
    for (src, dst), count in pair_count.items():
        make_relation(state, src, dst, "COMUNICACION", source="CDR limpio", source_type="IMPORTADO", description="Relación operacional observada; no identifica parentesco ni titularidad.", confidence="CONFIRMADO", evidence_ids=pair_evidence[(src, dst)], support_count=count)
    # Manual names are intentionally disconnected until a user creates an explicit relation.
    for person in manual_persons or []:
        add_entity(state, "PERSONA", person, source_type="MANUAL", source_detail="Alta manual", confidence="PENDIENTE", notes="Identidad pendiente de acreditar.")
    for number in target_norm:
        if number in phone_ids:
            state["targets"].append(phone_ids[number])
    state["targets"] = sorted(set(state["targets"]))
    append_audit(state, "CONSTRUIR_MAPA", f"{len(state['entities'])} entidades, {len(state['relationships'])} relaciones y {len(state['events'])} eventos.")
    return state


def state_from_legacy_graph(legacy) -> dict:
    """Migrate the previous (nodes, edges, evidence) session object in memory."""
    try:
        nodes, edges, evidence = legacy
    except (TypeError, ValueError):
        return new_state()
    state = new_state("Grafo migrado")
    nodes = nodes if isinstance(nodes, pd.DataFrame) else pd.DataFrame(nodes or [])
    edges = edges if isinstance(edges, pd.DataFrame) else pd.DataFrame(edges or [])
    for _, row in nodes.fillna("").iterrows():
        typ = "TELEFONO" if norm_text(row.get("tipo", "")) in {"LINEA", "TELEFONO", "MSISDN"} else "PERSONA"
        created = add_entity(state, typ, row.get("label") or row.get("id"), source_type="IMPORTADO", source_detail="Grafo legado", confidence="PENDIENTE", notes=text_value(row.get("titular")) or text_value(row.get("usuario")))
        # Keep legacy IDs verbatim so old sessions and tests can still focus a node by ID.
        original_id = text_value(row.get("id"))
        if original_id:
            match = next((item for item in state["entities"] if item["entity_id"] == created), None)
            if match:
                match["entity_id"] = original_id
    ids = {e["entity_id"] for e in state["entities"]}
    lookup = {normalize_identifier(e["label"]): e["entity_id"] for e in state["entities"]}
    for _, row in edges.fillna("").iterrows():
        src = lookup.get(normalize_identifier(row.get("source")), text_value(row.get("source")))
        dst = lookup.get(normalize_identifier(row.get("target")), text_value(row.get("target")))
        if src in ids and dst in ids:
            make_relation(state, src, dst, "COMUNICACION", source="Grafo legado", source_type="IMPORTADO", support_count=int(pd.to_numeric(row.get("peso_eventos", 1), errors="coerce") or 1))
    if isinstance(evidence, pd.DataFrame):
        for _, row in evidence.fillna("").iterrows():
            state["evidences"].append({
                "evidence_id": short_id("EVD"), "evidence_type": "GRAFO_LEGADO", "title": text_value(row.get("archivo_origen", "Evidencia legado")),
                "source": "Grafo legado", "file_name": text_value(row.get("archivo_origen")), "sheet_name": "", "row_number": text_value(row.get("fila_excel")),
                "source_hash": "", "captured_at": now_local(), "created_by": user_name(), "description": "Migrado sin inferir identidad.",
                "raw_json": json.dumps({text_value(k): text_value(v) for k, v in row.to_dict().items()}, ensure_ascii=False, default=str),
            })
    append_audit(state, "MIGRAR_GRAFO_LEGADO", "Se conservó el grafo anterior como entidades y comunicación observada.")
    return state


def preserve_manual_context(previous: dict, rebuilt: dict) -> dict:
    """Refresh observed CDR data while keeping documented identities and their support."""
    manual_relations = [copy.deepcopy(row) for row in previous.get("relationships", []) if row.get("source_type") == "MANUAL"]
    keep_ids = {row["entity_id"] for row in previous.get("entities", []) if row.get("source_type") == "MANUAL" or row.get("entity_type") == "PERSONA"}
    for row in manual_relations:
        keep_ids.update((row["source_id"], row["target_id"]))
    new_lookup = entity_lookup(rebuilt)
    needed_evidence = set()
    for row in previous.get("entities", []):
        if row["entity_id"] not in keep_ids:
            continue
        needed_evidence.update(filter(None, text_value(row.get("evidence_ids")).split(",")))
        if row["entity_id"] not in new_lookup:
            rebuilt["entities"].append(copy.deepcopy(row))
        else:
            current = new_lookup[row["entity_id"]]
            ids = set(filter(None, text_value(current.get("evidence_ids")).split(","))) | set(filter(None, text_value(row.get("evidence_ids")).split(",")))
            current["evidence_ids"] = ",".join(sorted(ids))
            current["metadata"] = json.dumps({**entity_metadata(current), **entity_metadata(row)}, ensure_ascii=False)
            if row.get("notes"):
                current["notes"] = row["notes"]
    for row in manual_relations:
        needed_evidence.update(filter(None, text_value(row.get("evidence_ids")).split(",")))
    existing_evidence = {row["evidence_id"] for row in rebuilt.get("evidences", [])}
    rebuilt["evidences"].extend(copy.deepcopy(row) for row in previous.get("evidences", [])
        if row["evidence_id"] not in existing_evidence and (row["evidence_id"] in needed_evidence or row.get("evidence_type") == "MANUAL"))
    rebuilt["relationships"].extend(manual_relations)
    rebuilt["assets"] = copy.deepcopy(previous.get("assets", {}))
    rebuilt["entity_history"] = copy.deepcopy(previous.get("entity_history", []))
    rebuilt["canvas_positions"] = copy.deepcopy(previous.get("canvas_positions", {}))
    rebuilt["canvas_sizes"] = copy.deepcopy(previous.get("canvas_sizes", {}))
    rebuilt["audit"] = copy.deepcopy(previous.get("audit", [])) + rebuilt["audit"]
    rebuilt["case_id"] = previous.get("case_id", rebuilt["case_id"])
    rebuilt["created_at"] = previous.get("created_at", rebuilt["created_at"])
    append_audit(rebuilt, "RENOVAR_CDR_CON_FICHAS", "Se renovaron los eventos CDR conservando fichas, fotos, atributos manuales y evidencia vinculada.")
    return rebuilt


def project_from_upload(upload) -> dict:
    payload = upload.getvalue() if hasattr(upload, "getvalue") else bytes(upload)
    name = text_value(getattr(upload, "name", ""))
    if name.lower().endswith(".json"):
        data = json.loads(payload.decode("utf-8"))
        if "identity_state" in data:
            return data["identity_state"]
        if "entities" in data or "ENTIDADES" in data:
            aliases = {"entidades": "entities", "relaciones": "relationships", "eventos": "events", "soporte_cdr": "support", "evidencias": "evidences", "auditoria": "audit"}
            normalized = {aliases.get(str(k).lower(), str(k).lower()): v for k, v in data.items()}
            return {**new_state(normalized.get("case_name", "Proyecto importado")), **{k: v for k, v in normalized.items() if k in {"entities", "relationships", "events", "support", "evidences", "audit", "targets", "case_id", "case_name", "dedup_tolerance"}}}
        if "nodos" in data or "aristas" in data:
            return state_from_legacy_graph((pd.DataFrame(data.get("nodos", [])), pd.DataFrame(data.get("aristas", [])), pd.DataFrame(data.get("evidencia", []))))
        raise ValueError("JSON sin hojas de identidad reconocibles.")
    book = pd.ExcelFile(BytesIO(payload))
    if "PROYECTO_JSON" in book.sheet_names:
        # Excel cells are limited to 32,767 characters. The complete project,
        # including originals and revision history, uses ordered 30k chunks.
        snapshot = pd.read_excel(book, sheet_name="PROYECTO_JSON", dtype=str, keep_default_na=False)
        snapshot = snapshot.assign(_part=pd.to_numeric(snapshot["parte"], errors="raise")).sort_values("_part")
        encoded = "".join(snapshot["contenido"].tolist())
        packed = base64.b64decode(encoded, validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(packed, 256 * 1024 * 1024 + 1)
        if not decoder.eof or len(raw) > 256 * 1024 * 1024:
            raise ValueError("El proyecto supera 256 MB descomprimido o está incompleto.")
        if not len(snapshot) or file_hash(raw) != snapshot.iloc[0]["sha256"]:
            raise ValueError("El expediente no supera la comprobación de integridad.")
        return json.loads(raw.decode("utf-8"))["identity_state"]
    frames = {sheet.upper(): pd.read_excel(book, sheet_name=sheet, dtype=str, keep_default_na=False).fillna("") for sheet in book.sheet_names}
    if "ENTIDADES" not in frames and "NODOS" in frames:
        return state_from_legacy_graph((frames["NODOS"].rename(columns={"label": "label"}), frames.get("ARISTAS", pd.DataFrame()), frames.get("EVIDENCIA_ORIGINAL", pd.DataFrame())))
    state = new_state(name.rsplit(".", 1)[0] or "Proyecto importado")
    mapping = {"ENTIDADES": "entities", "RELACIONES": "relationships", "EVENTOS": "events", "SOPORTE_CDR": "support", "EVIDENCIAS": "evidences", "AUDITORIA": "audit", "IMPORTACIONES": "imports"}
    for sheet, key in mapping.items():
        if sheet in frames:
            records = frames[sheet].to_dict("records")
            state[key] = records
    return state


def get_state() -> dict | None:
    state = st.session_state.get("gm_identity_state")
    if isinstance(state, dict) and "entities" in state:
        return state
    legacy = st.session_state.get("gm_graph")
    if legacy is not None:
        state = state_from_legacy_graph(legacy)
        st.session_state["gm_identity_state"] = state
        return state
    return None


def set_state(state: dict) -> None:
    previous = st.session_state.get("gm_identity_state", {})
    changed_case = previous.get("case_id") != state.get("case_id")
    state["canvas_revision"] = max(int(state.get("canvas_revision", 0)), int(previous.get("canvas_revision", 0)) + 1)
    st.session_state["gm_identity_state"] = state
    if changed_case:
        for key in ("gm_graph_focus", "gm_graph_compare", "gm_graph_depth", "gm_graph_minimum", "gm_graph_sources", "gm_person_select"):
            st.session_state.pop(key, None)
    # The tuple keeps backward compatibility with prior tests and saved sessions.
    entities = frame_from_records(state.get("entities", []), ENTITY_COLUMNS)
    relations = frame_from_records(state.get("relationships", []), RELATION_COLUMNS)
    nodes = entities.rename(columns={"entity_id": "id", "entity_type": "tipo"})[["id", "label", "tipo", "notes"]].rename(columns={"notes": "titular"})
    edges = relations.rename(columns={"source_id": "source", "target_id": "target", "support_count": "peso_eventos", "relation_type": "tipo"})[["source", "target", "tipo", "peso_eventos"]]
    st.session_state["gm_graph"] = (nodes, edges, frame_from_records(state.get("support", []), SUPPORT_COLUMNS))
    st.session_state["gm_graph_revision"] = st.session_state.get("gm_graph_revision", 0) + 1


def entity_lookup(state: dict) -> dict[str, dict]:
    return {x["entity_id"]: x for x in state.get("entities", [])}


PROFILE_FIELDS = (
    ("alias", "Alias"), ("role", "Cargo / función"), ("organization", "Organización"),
    ("birth_date", "Fecha de nacimiento"), ("nationality", "Nacionalidad"),
    ("identification", "Identificaciones / referencias"), ("address", "Domicilio declarado"),
    ("occupation", "Ocupación"), ("emails", "Correos electrónicos"),
    ("profiles", "Perfiles digitales"), ("traits", "Señas particulares"),
    ("other_details", "Otros datos documentados"),
)


def entity_metadata(entity: dict) -> dict:
    value = entity.get("metadata", {})
    if isinstance(value, dict):
        return copy.deepcopy(value)
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def prepare_portrait(upload) -> dict:
    """Keep the original and create a small local preview; no external image URL."""
    from PIL import Image, ImageOps

    raw = upload.getvalue()
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise ValueError("La fotografía debe pesar entre 1 byte y 5 MB.")
    try:
        with Image.open(BytesIO(raw)) as original:
            kind = original.format
            if kind not in {"PNG", "JPEG", "WEBP"} or original.width * original.height > 20_000_000:
                raise ValueError("Usa una imagen PNG, JPG o WebP de hasta 20 megapíxeles.")
            original.load()
            preview = ImageOps.exif_transpose(original).convert("RGB")
            preview.thumbnail((512, 512))
            buf = BytesIO()
            preview.save(buf, "JPEG", quality=86)
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError("No se pudo leer esa fotografía. Prueba con PNG, JPG o WebP.") from error
    return {"asset_id": "FOTO_" + file_hash(raw)[:20], "file_name": text_value(getattr(upload, "name", "foto")),
            "mime_type": {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[kind],
            "sha256": file_hash(raw), "data": base64.b64encode(raw).decode("ascii"),
            "preview": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")}


def portrait_uri(state: dict, entity: dict) -> str:
    asset_id = entity_metadata(entity).get("photo_asset", "")
    candidate = text_value(state.get("assets", {}).get(asset_id, {}).get("preview"))
    return candidate if len(candidate) <= 1_000_000 and re.fullmatch(r"data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+", candidate) else ""


def save_person_profile(state: dict, selected_id: str, label: str, metadata: dict, *,
                        confidence: str, source: str, notes: str, evidence_ids: list[str],
                        portrait: dict | None = None, photo_source: str = "", remove_photo: bool = False) -> str:
    """Explicit edit by ID, preserving previous records and photo assets in history."""
    if not label.strip() or not source.strip():
        raise ValueError("Escribe el nombre y una fuente para la ficha.")
    if portrait and not photo_source.strip():
        raise ValueError("Indica la fuente de la fotografía.")
    record = entity_lookup(state).get(selected_id) if selected_id else None
    if selected_id and (not record or record.get("entity_type") != "PERSONA"):
        raise ValueError("Selecciona una persona existente.")
    before = copy.deepcopy(record) if record else None
    if record is None:
        selected_id = add_entity(state, "PERSONA", label, source_type="MANUAL", source_detail=source, confidence=confidence)
        record = entity_lookup(state)[selected_id]
    merged = {**entity_metadata(record), **metadata, "updated_at": now_local(), "updated_by": user_name()}
    linked_evidence = set(filter(None, evidence_ids))
    if remove_photo:
        merged.pop("photo_asset", None)
    if portrait:
        state.setdefault("assets", {})[portrait["asset_id"]] = {**portrait, "source": photo_source, "captured_at": now_local()}
        merged["photo_asset"] = portrait["asset_id"]
        photo_evidence = add_manual_evidence_to_state(state, f"Fotografía · {label}", photo_source,
            "Original conservado en el expediente; miniatura para representación del nodo.",
            json.dumps({"asset_id": portrait["asset_id"], "sha256": portrait["sha256"], "file_name": portrait["file_name"]}, ensure_ascii=False))
        linked_evidence.add(photo_evidence)
    record.update({"label": label.strip(), "normalized": normalize_identifier(label), "confidence": confidence,
                   "source_detail": source.strip(), "notes": notes.strip(), "evidence_ids": ",".join(sorted(linked_evidence)),
                   "metadata": json.dumps(merged, ensure_ascii=False)})
    state.setdefault("entity_history", []).append({"revision_id": short_id("REV"), "entity_id": selected_id,
        "timestamp": now_local(), "user": user_name(), "before": before, "after": copy.deepcopy(record)})
    append_audit(state, "EDITAR_FICHA" if before else "CREAR_FICHA", f"{label} · fuente: {source}", object_id=selected_id)
    return selected_id


def entity_label(state: dict, entity_id_value: str) -> str:
    row = entity_lookup(state).get(entity_id_value, {})
    return f"{ENTITY_ICONS.get(row.get('entity_type', ''), '•')} {row.get('label', entity_id_value)}"


def relation_ids(state: dict, entity_id_value: str) -> set[str]:
    ids = {entity_id_value}
    changed = True
    while changed:
        changed = False
        for relation in state.get("relationships", []):
            if relation.get("status") == "DESCARTADA":
                continue
            if relation.get("source_id") in ids or relation.get("target_id") in ids:
                before = len(ids)
                ids.update((relation.get("source_id", ""), relation.get("target_id", "")))
                changed = changed or before != len(ids)
    return ids


def relationship_graph(state: dict, focus: str = "", depth: int = 1, minimum: int = 0, source_filter: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    entities = frame_from_records(state.get("entities", []), ENTITY_COLUMNS)
    relations = frame_from_records(state.get("relationships", []), RELATION_COLUMNS)
    if source_filter is not None:
        relations = relations[relations["source_type"].isin(source_filter)]
    relations = relations[(relations["status"] != "DESCARTADA") & (relations["confidence"] != "DESCARTADO")]
    # A CDR count should not remove a documented family/identity relationship.
    relations = relations[(relations["relation_type"] != "COMUNICACION") | (pd.to_numeric(relations["support_count"], errors="coerce").fillna(0) >= minimum)]
    if focus:
        visible = {focus}
        frontier = {focus}
        for _ in range(max(1, depth)):
            nxt = set(relations.loc[relations["source_id"].isin(frontier) | relations["target_id"].isin(frontier), "source_id"].tolist()) | set(relations.loc[relations["source_id"].isin(frontier) | relations["target_id"].isin(frontier), "target_id"].tolist())
            nxt -= visible
            visible |= nxt
            frontier = nxt
        relations = relations[relations["source_id"].isin(visible) & relations["target_id"].isin(visible)]
        entities = entities[entities["entity_id"].isin(visible)]
    return entities.copy(), relations.copy()


def apply_canvas_action(state: dict, event: dict) -> tuple[dict, dict]:
    """Apply one explicit browser action atomically; reject stale or replayed edits."""
    if not isinstance(event, dict) or event.get("case_id") != state.get("case_id"):
        raise ValueError("El diagrama pertenece a otro expediente. Recarga la vista.")
    action_id = text_value(event.get("action_id"))
    if not action_id or len(action_id) > 120:
        raise ValueError("Acción sin identificador válido.")
    if action_id in state.get("canvas_applied", []):
        return state, {"id": action_id, "ok": True, "message": "Cambio ya guardado.", "duplicate": True}
    if event.get("revision") != state.get("canvas_revision", 0):
        raise ValueError("El expediente cambió. Revisa la vista actual y repite el cambio.")
    mode = event.get("mode", "red")
    if mode not in {"red", "organigrama"}:
        raise ValueError("Distribución desconocida.")
    operation = event.get("operation")
    updated = copy.deepcopy(state)
    lookup = entity_lookup(updated)
    selected = ""
    message = "Cambio guardado."
    values = event.get("values") or {}
    if not isinstance(values, dict):
        raise ValueError("Valores de ficha inválidos.")
    if operation in {"create", "edit"}:
        selected = text_value(event.get("entity_id"))
        current = lookup.get(selected, {})
        if operation == "edit" and not current:
            raise ValueError("Ese actor ya no está disponible.")
        kind = current.get("entity_type") if current else text_value(values.get("entity_type"))
        label = text_value(values.get("label"))
        source = text_value(values.get("source"), "Captura manual")
        confidence = text_value(values.get("confidence"), "PENDIENTE")
        if kind not in ENTITY_TYPES or not label or len(label) > 500 or confidence not in CONFIDENCE_LEVELS:
            raise ValueError("Revisa el tipo, el nombre y la confianza del actor.")
        if mode == "organigrama" and kind != "PERSONA":
            raise ValueError("Añade otros tipos de actor desde Red de vínculos.")
        metadata = values.get("metadata") or {}
        if not isinstance(metadata, dict) or any(key not in {x[0] for x in PROFILE_FIELDS} | {"visual_color", "visual_shape", "visual_group"} for key in metadata):
            raise ValueError("Campos de ficha inválidos.")
        metadata = {key: text_value(value)[:10000] for key, value in metadata.items()}
        if metadata.get("visual_color") and not re.fullmatch(r"#[0-9A-Fa-f]{6}", metadata["visual_color"]):
            raise ValueError("Color de actor inválido.")
        if metadata.get("visual_shape") not in {None, "", "circle", "hexagon"}:
            raise ValueError("Forma de actor inválida.")
        evidence_ids = values.get("evidence_ids", [])
        allowed_evidence = {row["evidence_id"] for row in updated.get("evidences", [])}
        if not isinstance(evidence_ids, list) or not set(evidence_ids).issubset(allowed_evidence):
            raise ValueError("La evidencia seleccionada no pertenece al expediente.")
        portrait = None
        if values.get("photo_data"):
            encoded = text_value(values["photo_data"])
            if len(encoded) > 7_000_000:
                raise ValueError("La fotografía supera 5 MB.")
            try:
                raw = base64.b64decode(encoded.split(",", 1)[-1], validate=True)
                upload = BytesIO(raw)
                upload.name = text_value(values.get("photo_name"), "fotografia")
                portrait = prepare_portrait(upload)
            except (ValueError, OSError) as error:
                raise ValueError("Fotografía inválida: " + str(error)) from error
        if kind == "PERSONA":
            selected = save_person_profile(updated, selected if current else "", label, metadata, confidence=confidence,
                source=source, notes=text_value(values.get("notes")), evidence_ids=evidence_ids, portrait=portrait,
                photo_source=text_value(values.get("photo_source"), source), remove_photo=bool(values.get("remove_photo")))
        elif current:
            # Phone/CDR identifiers remain immutable; edit annotations, not observed IDs.
            if kind in {"TELEFONO", "IMEI", "IMSI/SIM", "CORREO ELECTRONICO", "ANTENA"} and label != current["label"]:
                raise ValueError("El identificador técnico no se renombra. Crea otro actor si es distinto.")
            before = copy.deepcopy(current)
            current["label"] = label
            current["normalized"] = normalize_identifier(label)
            if current.get("source_type") == "MANUAL":
                current["source_detail"] = source
                current["confidence"] = confidence
            merged = {**entity_metadata(current), **metadata}
            if values.get("remove_photo"):
                merged.pop("photo_asset", None)
            current["metadata"] = json.dumps(merged, ensure_ascii=False)
            current["notes"] = text_value(values.get("notes"))
            current["evidence_ids"] = ",".join(sorted(set(filter(None, text_value(current.get("evidence_ids")).split(","))) | set(evidence_ids)))
            updated.setdefault("entity_history", []).append({"revision_id": short_id("REV"), "entity_id": selected,
                "timestamp": now_local(), "user": user_name(), "before": before, "after": copy.deepcopy(current)})
            append_audit(updated, "ANOTAR_ACTOR", label, object_id=selected)
        else:
            selected = add_entity(updated, kind, label, source_type="MANUAL", source_detail=source, confidence=confidence,
                notes=text_value(values.get("notes")), evidence_ids=evidence_ids, metadata=metadata)
            append_audit(updated, "CREAR_ACTOR_VISUAL", f"{kind}: {label}", object_id=selected)
        if kind != "PERSONA" and portrait:
            row = entity_lookup(updated)[selected]
            updated.setdefault("assets", {})[portrait["asset_id"]] = {**portrait, "source": text_value(values.get("photo_source"), source)}
            row["metadata"] = json.dumps({**entity_metadata(row), "photo_asset": portrait["asset_id"]}, ensure_ascii=False)
            eid = add_manual_evidence_to_state(updated, f"Imagen del actor · {label}", text_value(values.get("photo_source"), source), "Imagen original conservada en el expediente.", json.dumps({"asset_id": portrait["asset_id"], "sha256": portrait["sha256"]}))
            row["evidence_ids"] = ",".join(sorted(set(filter(None, text_value(row.get("evidence_ids")).split(","))) | {eid}))
            if operation == "edit" and updated.get("entity_history") and updated["entity_history"][-1].get("entity_id") == selected:
                updated["entity_history"][-1]["after"] = copy.deepcopy(row)
        message = "Actor creado. Puedes conectarlo con otro." if operation == "create" else "Ficha actualizada."
    elif operation == "connect":
        a, b = text_value(values.get("source_id")), text_value(values.get("target_id"))
        kind = text_value(values.get("relation_type"))
        confidence = text_value(values.get("confidence"), "PENDIENTE")
        if a not in lookup or b not in lookup or a == b or kind not in RELATION_TYPES or confidence not in CONFIDENCE_LEVELS:
            raise ValueError("Selecciona dos actores distintos y un vínculo válido.")
        if kind in (*PERSONAL_RELATIONS, *HIERARCHY_RELATIONS) and any(lookup[key]["entity_type"] != "PERSONA" for key in (a, b)):
            raise ValueError("Ese vínculo requiere dos personas.")
        evidence_ids = values.get("evidence_ids") or []
        if not isinstance(evidence_ids, list) or not set(evidence_ids).issubset({row["evidence_id"] for row in updated.get("evidences", [])}):
            raise ValueError("La evidencia seleccionada no pertenece al expediente.")
        source = text_value(values.get("source"), "Captura manual")
        description = text_value(values.get("description"))
        visual_color = text_value(values.get("visual_color"), "#d65761")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", visual_color):
            raise ValueError("Color de vínculo inválido.")
        duplicate = any(row.get("source_id") == a and row.get("target_id") == b and row.get("relation_type") == kind
            and row.get("source") == source and row.get("description") == description and row.get("confidence") == confidence
            and row.get("status") != "DESCARTADA" and row.get("source_type") == "MANUAL" for row in updated["relationships"])
        if duplicate:
            message = "Este vínculo ya estaba registrado."
        else:
            relation_id = add_manual_relation_to_state(updated, a, b, kind, source=source, description=description,
                confidence=confidence, evidence_ids=evidence_ids)
            next(row for row in updated["relationships"] if row["relation_id"] == relation_id)["visual_color"] = visual_color
            message = "Vínculo guardado. Su dirección va del origen al destino."
        selected = a
    elif operation == "discard":
        relation_id = text_value(values.get("relation_id"))
        row = next((r for r in updated["relationships"] if r["relation_id"] == relation_id), None)
        if not row or row.get("source_type") != "MANUAL":
            raise ValueError("Solo puedes descartar aquí vínculos manuales.")
        row["status"] = "DESCARTADA"
        append_audit(updated, "DESCARTAR_VINCULO_VISUAL", row["relation_type"], object_id=relation_id)
        message = "Vínculo descartado; se conserva en el historial."
    elif operation not in {"move", "arrange"}:
        raise ValueError("Operación del editor no reconocida.")

    if operation == "arrange":
        updated.setdefault("canvas_positions", {})[mode] = {}
        updated.setdefault("canvas_sizes", {}).pop(mode, None)
        append_audit(updated, "ORDENAR_DIAGRAMA", mode)
        message = "Diagrama ordenado automáticamente."
    else:
        positions = event.get("positions", {})
        if not isinstance(positions, dict) or len(positions) > 500:
            raise ValueError("Posiciones de diagrama inválidas.")
        all_ids = set(entity_lookup(updated))
        checked = {}
        for key, point in positions.items():
            if key not in all_ids or not isinstance(point, list) or len(point) != 2:
                raise ValueError("Posición sin actor válido.")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 100000 for v in point):
                raise ValueError("Posición fuera del lienzo.")
            checked[key] = [float(point[0]), float(point[1])]
        if operation == "create" and selected:
            point = event.get("point")
            if not isinstance(point, list) or len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 100000 for v in point):
                raise ValueError("Punto de creación inválido.")
            checked[selected] = point
        updated.setdefault("canvas_positions", {}).setdefault(mode, {}).update(checked)
        size = event.get("size", [1120, 680])
        if not isinstance(size, list) or len(size) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 200 <= v <= 110000 for v in size):
            raise ValueError("Dimensiones del lienzo inválidas.")
        updated.setdefault("canvas_sizes", {})[mode] = size
        if operation == "move":
            append_audit(updated, "MOVER_ACTORES", f"{len(checked)} posiciones guardadas · {mode}")
            message = "Posiciones guardadas."
    updated["canvas_revision"] = int(state.get("canvas_revision", 0)) + 1
    if selected:
        updated["canvas_selection"] = selected
    updated["canvas_applied"] = (state.get("canvas_applied", []) + [action_id])[-1000:]
    return updated, {"id": action_id, "ok": True, "message": message, "selected": selected, "operation": operation}


@st.cache_resource(show_spinner=False)
def canvas_component(markup: str):
    """Serve a bundled component generated by this one Python module."""
    directory = Path(tempfile.mkdtemp(prefix="sentinel_canvas_5_2_"))
    (directory / "index.html").write_text(markup.replace("__GRAPH_DATA__", "null"), encoding="utf-8")
    return components.declare_component("sentinel_canvas_5_2", path=str(directory))


def render_canvas_editor(state: dict, payload: dict) -> None:
    payload["editable"] = True
    payload["revision"] = int(state.get("canvas_revision", 0))
    payload["case_id"] = state.get("case_id")
    payload["actor_types"] = list(ENTITY_TYPES)
    payload["relation_types"] = list(RELATION_TYPES)
    payload["hierarchy_types"] = list(HIERARCHY_RELATIONS)
    payload["personal_types"] = list(PERSONAL_RELATIONS)
    payload["profile_fields"] = list(PROFILE_FIELDS)
    payload["confidence_levels"] = list(CONFIDENCE_LEVELS)
    payload["evidence_options"] = [{"id": row["evidence_id"], "title": row.get("title", row["evidence_id"])} for row in state.get("evidences", []) if row.get("evidence_type") == "MANUAL"]
    ack_key = "gm_canvas_ack_" + state["case_id"]
    event = canvas_component(DIAGRAM_HTML)(payload=payload, ack=st.session_state.get(ack_key), default=None, key="gm_canvas_" + state["case_id"] + "_" + payload["mode"] + "_" + APP_VERSION)
    if not isinstance(event, dict) or not event.get("action_id") or event["action_id"] == (st.session_state.get(ack_key) or {}).get("id"):
        return
    try:
        updated, ack = apply_canvas_action(state, event)
        if not ack.get("duplicate"):
            set_state(updated)
            if event.get("operation") == "create":
                st.session_state["gm_canvas_reveal"] = ack.get("selected")
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        ack = {"id": event["action_id"], "ok": False, "message": str(error)}
    st.session_state[ack_key] = ack
    st.rerun()


def diagram_layout(rows: list[dict], relations: list[dict], mode: str, focus: str = "", compare: str = "") -> tuple[dict, float, float, list[str]]:
    """Deterministic layouts; hierarchy comes only from explicit hierarchy edges."""
    ids = [row["entity_id"] for row in rows]
    if not ids:
        return {}, 1120, 620, []
    neighbours = {key: set() for key in ids}
    for rel in relations:
        a, b = rel.get("source_id"), rel.get("target_id")
        if a in neighbours and b in neighbours and a != b:
            neighbours[a].add(b)
            neighbours[b].add(a)
    messages = []
    if mode == "organigrama":
        children = {key: set() for key in ids}
        incoming = {key: 0 for key in ids}
        for rel in relations:
            if rel.get("relation_type") not in HIERARCHY_RELATIONS:
                continue
            a, b = rel["source_id"], rel["target_id"]
            if rel["relation_type"] in UPWARD_RELATIONS:
                a, b = b, a
            if a in children and b in incoming and a != b and b not in children[a]:
                children[a].add(b)
                incoming[b] += 1
        levels = {}
        queue = sorted(key for key in ids if incoming[key] == 0)
        for key in queue:
            levels[key] = 0
        cursor = 0
        while cursor < len(queue):
            key = queue[cursor]
            cursor += 1
            for child in sorted(children[key]):
                levels[child] = max(levels.get(child, 0), levels[key] + 1)
                incoming[child] -= 1
                if incoming[child] == 0:
                    queue.append(child)
        pending = [key for key in ids if key not in queue]
        if pending:
            # Do not invent a hierarchy for cycles or their descendants.
            last = max(levels.values(), default=0) + 1
            levels.update({key: last for key in pending})
            messages.append("Hay un ciclo jerárquico. Los nodos afectados aparecen al final, sin nivel validado; revisa sus relaciones.")
        connected = {key for key in ids if neighbours[key]}
        if connected and any(key not in connected for key in ids):
            last = max((levels[key] for key in connected), default=0) + 1
            for key in ids:
                if key not in connected:
                    levels[key] = last
            messages.append("Las personas sin relación jerárquica se muestran en la última fila; su posición no asigna un cargo.")
        groups = defaultdict(list)
        for key in ids:
            groups[levels[key]].append(key)
        width = max(1000, max(len(group) for group in groups.values()) * 230 + 80)
        height = max(540, len(groups) * 210 + 50)
        positions = {}
        for index, level in enumerate(sorted(groups)):
            group = groups[level]
            for col, key in enumerate(group):
                positions[key] = [width / 2 + (col - (len(group) - 1) / 2) * 230, (height / 2 - 30) if len(groups) == 1 else 86 + index * 210]
        return positions, width, height, messages

    ranked = sorted(ids, key=lambda key: (-len(neighbours[key]), ids.index(key)))
    primary = focus if focus in ids else next((r["entity_id"] for r in rows if r.get("entity_type") == "PERSONA" and neighbours[r["entity_id"]]), ranked[0])
    secondary = compare if compare in ids and compare != primary else ""
    if not secondary:
        others = [key for key in ranked if key != primary]
        radius = max(235, len(others) * 100 / (2 * math.pi))
        width, height = max(1120, radius * 2 + 360), max(620, radius * 2 + 180)
        positions = {primary: [width / 2, height / 2 - 15]}
        for index, key in enumerate(others):
            angle = -math.pi / 2 + 2 * math.pi * index / max(1, len(others))
            positions[key] = [width / 2 + radius * math.cos(angle), height / 2 - 15 + radius * math.sin(angle)]
        return positions, width, height, messages

    common = sorted(neighbours[primary] & neighbours[secondary] - {primary, secondary})
    def distances(root):
        result, frontier = {root: 0}, [root]
        for current in frontier:
            for candidate in sorted(neighbours[current]):
                if candidate not in result:
                    result[candidate] = result[current] + 1
                    frontier.append(candidate)
        return result
    left_dist, right_dist = distances(primary), distances(secondary)
    left, right = [], []
    for key in ranked:
        if key in {primary, secondary} or key in common:
            continue
        (left if left_dist.get(key, math.inf) <= right_dist.get(key, math.inf) else right).append(key)
    radius = max(245, max(len(left), len(right)) * 105 / math.pi, len(common) * 60)
    width, height = 4 * radius + 380, 2 * radius + 240
    lx, rx, cy = radius + 135, 3 * radius + 245, height / 2 - 10
    positions = {primary: [lx, cy], secondary: [rx, cy]}
    for index, key in enumerate(common):
        positions[key] = [width / 2, cy + (index - (len(common) - 1) / 2) * 120]
    for group, cx, sign in ((left, lx, -1), (right, rx, 1)):
        for index, key in enumerate(group):
            angle = -math.pi / 2 + math.pi * (index + .5) / max(len(group), 1)
            positions[key] = [cx + sign * radius * math.cos(angle), cy + radius * math.sin(angle)]
    return positions, width, height, messages


def diagram_payload(state: dict, entities: pd.DataFrame, relations: pd.DataFrame, *, focus: str = "", compare: str = "", mode: str = "red") -> dict:
    rows, rels = entities.to_dict("records"), relations.to_dict("records")
    positions, width, height, messages = diagram_layout(rows, rels, mode, focus, compare)
    saved = state.get("canvas_positions", {}).get(mode, {})
    for key in positions:
        point = saved.get(key)
        if isinstance(point, list) and len(point) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 100000 for v in point):
            positions[key] = point
    if saved:
        size = state.get("canvas_sizes", {}).get(mode, [width, height])
        if isinstance(size, list) and len(size) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) and 200 <= v <= 110000 for v in size):
            width, height = size
        width = max(width, max((point[0] + 150 for point in positions.values()), default=width))
        height = max(height, max((point[1] + 150 for point in positions.values()), default=height))
    lookup = entity_lookup(state)
    evidence_lookup = {row["evidence_id"]: row for row in state.get("evidences", [])}
    connections = defaultdict(list)
    for rel in state.get("relationships", []):
        for key, other in ((rel.get("source_id"), rel.get("target_id")), (rel.get("target_id"), rel.get("source_id"))):
            if key and other in lookup:
                connections[key].append({"id": other, "label": lookup[other].get("label", other),
                    "type": lookup[other].get("entity_type", ""), "direction": "→" if key == rel.get("source_id") else "←",
                    "relation": rel.get("relation_type", ""), "confidence": rel.get("confidence", ""),
                    "source": rel.get("source", ""), "source_detail": rel.get("source_detail", ""),
                    "source_type": rel.get("source_type", ""), "status": rel.get("status", ""),
                    "description": rel.get("description", ""), "evidence_ids": rel.get("evidence_ids", ""),
                    "start": rel.get("start_date", ""), "end": rel.get("end_date", "")})
    nodes = []
    for row in rows:
        metadata = entity_metadata(row)
        support_ids = set(filter(None, text_value(row.get("evidence_ids")).split(",")))
        for link in connections[row["entity_id"]]:
            support_ids.update(filter(None, text_value(link["evidence_ids"]).split(",")))
        nodes.append({**{k: text_value(row.get(k)) for k in ("entity_id", "entity_type", "label", "confidence", "source_type", "source_detail", "notes")},
            "photo": portrait_uri(state, row), "alias": text_value(metadata.get("alias")), "role": text_value(metadata.get("role")),
            "metadata": {key: text_value(metadata.get(key)) for key, _ in PROFILE_FIELDS},
            "visual_color": metadata.get("visual_color") if re.fullmatch(r"#[0-9A-Fa-f]{6}", text_value(metadata.get("visual_color"))) else "#216e7a",
            "visual_shape": "hexagon" if metadata.get("visual_shape") == "hexagon" else "circle", "visual_group": text_value(metadata.get("visual_group")),
            "own_evidence_ids": list(filter(None, text_value(row.get("evidence_ids")).split(","))),
            "organization": text_value(metadata.get("organization")), "fields": {label: text_value(metadata.get(key)) for key, label in PROFILE_FIELDS if text_value(metadata.get(key))},
            "x": positions[row["entity_id"]][0], "y": positions[row["entity_id"]][1],
            "icon": ENTITY_ICONS.get(row.get("entity_type"), "•"), "color": ENTITY_COLORS.get(row.get("entity_type"), "#64748b"),
            "links": connections[row["entity_id"]],
            "evidence": [{"id": key, "title": evidence_lookup.get(key, {}).get("title", key),
                          "source": evidence_lookup.get(key, {}).get("source", "")} for key in sorted(support_ids)]})
    # Consolidate repeated displayed edges, keeping every underlying relationship ID.
    edge_groups = {}
    for rel in rels:
        key = tuple(text_value(rel.get(k)) for k in ("source_id", "target_id", "relation_type", "source_type", "confidence", "visual_color"))
        if key not in edge_groups:
            edge_groups[key] = {**rel, "relation_ids": [], "records": 0}
            edge_groups[key]["visual_color"] = rel.get("visual_color") if re.fullmatch(r"#[0-9A-Fa-f]{6}", text_value(rel.get("visual_color"))) else ""
        edge_groups[key]["relation_ids"].append(rel["relation_id"])
        edge_groups[key]["records"] += 1
    return {"nodes": nodes, "edges": list(edge_groups.values()), "width": width, "height": height,
            "focus": focus, "compare": compare, "mode": mode, "messages": messages,
            "case_name": text_value(state.get("case_name"), "Mapa de identidad"), "version": APP_VERSION}


DIAGRAM_HTML = r'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}body{margin:0;color:#18334b;background:#fff;font-family:Inter,Arial,sans-serif;font-size:13px}
button,input{font:inherit}button{cursor:pointer}button:focus-visible,input:focus-visible,.node:focus-visible{outline:3px solid #22b8ac;outline-offset:3px}
#app{height:100vh;min-height:570px;border:1px solid #dbe5ed;border-radius:18px;overflow:hidden;background:#fbfdfe;display:flex;flex-direction:column}
.bar{display:flex;align-items:center;gap:8px;padding:14px 18px;border-bottom:1px solid #e0e9ef;background:#fff;flex-wrap:wrap}
.brand{font-size:10px;letter-spacing:2px;color:#158d89;font-weight:800}.title{margin:3px 0 0;font-size:15px;font-weight:750}
.tools{margin-left:auto;display:flex;gap:6px;align-items:center;flex-wrap:wrap}.tools button,.light{border:1px solid #dbe5ed;background:#fff;color:#29465b;border-radius:8px;padding:7px 10px}
.tools button:hover,.light:hover{background:#eef8f7;border-color:#73b9b4}.tools input{border:1px solid #dbe5ed;border-radius:8px;padding:8px;width:174px;min-width:90px}
.main{display:flex;flex:1;min-height:0;position:relative}.stage{flex:1;min-width:0;position:relative;background:radial-gradient(#e4ecf1 .7px,transparent .7px);background-size:18px 18px}
#canvas{width:100%;height:100%;display:block;touch-action:none;cursor:grab}#canvas:active{cursor:grabbing}
.node{cursor:pointer}.node text{pointer-events:none}.node.selected .halo{stroke:#119c94;stroke-width:4;fill:#d5f4ee}
.node.muted{opacity:.22}.edge.muted{opacity:.07}.edge{cursor:pointer}.edge:hover{opacity:1}
.edge-label{font:10px Arial,sans-serif;fill:#587086;paint-order:stroke;stroke:#fff;stroke-width:4px;stroke-linejoin:round}
.label{font:600 13px Arial,sans-serif;fill:#233e50;paint-order:stroke;stroke:#fff;stroke-width:4px;stroke-linejoin:round}
.sub{font:11px Arial,sans-serif;fill:#6c7f8e;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round}
.label.org{font-size:15px}.sub.org{font-size:13px}
.hint{position:absolute;left:14px;bottom:12px;font-size:11px;background:#ffffffed;padding:7px 10px;border-radius:7px;pointer-events:none;color:#6a7c8e}
#detail{width:300px;flex-shrink:0;overflow:auto;padding:20px;background:#fff;border-left:1px solid #e0e9ef}
#detail.hidden{display:none}#detail h2{font-size:21px;line-height:1.3;margin:12px 0 4px;overflow-wrap:anywhere}
#detail h3{font-size:10px;letter-spacing:1.7px;text-transform:uppercase;color:#63818c;border-top:1px solid #e6edf2;padding-top:18px;margin-top:20px}
#detail p{line-height:1.5;overflow-wrap:anywhere;white-space:pre-wrap}#detail dl{margin:16px 0}#detail dt{color:#738592;font-size:11px;margin-top:14px}#detail dd{margin:4px 0 0;line-height:1.5;overflow-wrap:anywhere;white-space:pre-wrap}
.portrait{width:78px;height:78px;object-fit:cover;border-radius:50%;border:3px solid #184a52;background:#eaf5f3}
.initials{display:grid;place-items:center;font-size:23px;color:#185f64}.badge{display:inline-block;font-size:10px;border-radius:5px;padding:5px 7px;margin:6px 4px 4px 0;background:#e8f5f2;color:#176b64}
.badge.pending{color:#926612;background:#fff3d6}.muted-text{color:#748694;font-size:11px;line-height:1.5}
.link-card{border:1px solid #e3ebf0;border-radius:10px;padding:11px;margin:8px 0;background:#fcfdfe}
.link-card button{border:0;background:none;text-align:left;padding:0;font-weight:600;color:#246886;overflow-wrap:anywhere}
.link-card p{font-size:11px;margin:6px 0 0}.footer{display:flex;gap:18px;align-items:center;padding:11px 17px;border-top:1px solid #e0e9ef;background:#fff;font-size:10px;color:#6b7f8d;flex-wrap:wrap}
.swatch{display:inline-block;width:16px;border-top:2px solid;vertical-align:middle;margin-right:5px}.footer .count{margin-left:auto}
#message{display:none;padding:9px 16px;background:#fff6de;color:#816011;font-size:12px}
#palette{display:none;width:126px;flex-shrink:0;padding:14px 9px;border-right:1px solid #dce8ee;background:#f3f8fa;overflow:auto}
#palette h3{font-size:13px;margin:0 0 4px}#palette p{font-size:10px;color:#6f8592;line-height:1.4;margin:0 0 12px}
.actor-tool{display:flex;align-items:center;gap:7px;width:100%;padding:9px 6px;margin:5px 0;border:1px solid #dbe7ed;border-radius:9px;background:white;color:#244858;text-align:left;cursor:grab;font-size:10px;line-height:1.25}
.actor-tool:hover{border-color:#16968c;background:#ecf8f5}.actor-tool svg{width:25px;height:25px;flex-shrink:0}.actor-tool:disabled{opacity:.4;cursor:default}
.editor-only{display:none}.editor .editor-only{display:inline-block}.editor #palette{display:block}
#editorNote{display:none;padding:10px 17px;background:#edf8f5;border-bottom:1px solid #d5e9e3;color:#29655d;font-size:12px;line-height:1.4}
.editor #editorNote{display:block}.node .connect-port{cursor:crosshair;fill:#fff;stroke:#12867e;stroke-width:2}.node .connect-port:hover{fill:#a4e5db}
#detail form label{display:block;font-size:11px;color:#55717e;margin:12px 0 5px}
#detail form input:not([type=checkbox]),#detail form select,#detail form textarea{width:100%;font:13px Arial,sans-serif;border:1px solid #ccdce4;border-radius:7px;padding:8px;background:#fff;color:#17384c;box-sizing:border-box}
#detail form input:read-only{background:#eef2f5}#detail form input[type=color]{height:35px;padding:3px}
#detail form textarea{min-height:70px;resize:vertical}#detail form select[multiple]{min-height:65px}
#detail .primary{padding:10px 12px;background:#137e77;color:#fff;border:0;border-radius:8px;font-weight:600;margin:14px 7px 0 0;cursor:pointer}
#detail .danger{color:#ac3544;border:1px solid #e9bac1;background:#fff;border-radius:8px;padding:8px;margin-top:15px}
#detail button:disabled{opacity:.6;cursor:wait}.editor .hint{display:none}#emptyHelp{fill:#718992;font:16px Arial,sans-serif}
@media(max-width:760px){#palette{width:82px;padding:10px 5px}.actor-tool{flex-direction:column;text-align:center;padding:8px 2px;font-size:9px}#palette p{font-size:9px}.editor #detail{width:285px}}
@media(max-width:760px){#detail{width:250px;position:absolute;right:0;top:0;bottom:0;box-shadow:-6px 0 20px #1232}.tools{margin-left:0}.bar{padding:10px}.hint{max-width:60%}.footer{gap:9px}}
</style></head><body><div id="app">
<header class="bar"><div><div class="brand">SENTINEL · IDENTIDADES</div><div class="title" id="viewTitle"></div></div>
<div class="tools"><input id="search" type="search" placeholder="Buscar nombre o alias" aria-label="Buscar entidad">
<button id="zoomIn" aria-label="Acercar" title="Acercar">+</button><button id="zoomOut" aria-label="Alejar" title="Alejar">−</button>
<button id="fit" title="Restaurar encuadre y selección">Encuadrar</button><button id="labels" aria-pressed="false" title="Mostrar tipos de relación">Vínculos</button>
<button id="connect" class="editor-only" title="Selecciona origen y destino">Conectar</button><button id="arrange" class="editor-only" title="Ordenar los actores automáticamente">Ordenar</button>
<button id="export" title="Descargar la vista actual con fotografías">SVG ↓</button></div></header>
<div id="editorNote" role="status"></div><div id="message" role="status"></div><div class="main"><nav id="palette" aria-label="Paleta de actores"></nav><section class="stage">
<svg id="canvas" xmlns="http://www.w3.org/2000/svg" role="group" aria-label="Diagrama interactivo de identidades">
<defs id="defs"><marker id="arrowBlue" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M0,0 L8,4 L0,8" fill="#7eaacb"/></marker>
<marker id="arrowRed" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M0,0 L9,4.5 L0,9" fill="#d65761"/></marker>
<marker id="arrowGold" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M0,0 L8,4 L0,8" fill="#cc922b"/></marker></defs>
<g id="viewport"><g id="edges"></g><g id="nodes"></g></g></svg>
<div class="hint">Clic: ficha · Arrastra: mover nodo o lienzo · Rueda: zoom</div></section>
<aside id="detail" class="hidden" aria-live="polite" aria-label="Ficha de entidad"></aside></div>
<footer class="footer"><span>Color de vínculos personalizable · consulta origen en la ficha</span>
<span><i class="swatch" style="color:#cc922b;border-top-style:dashed"></i>Inferido</span><span>Punteado: probable o pendiente</span><span class="count" id="count"></span></footer></div>
<script id="graphData" type="application/json">__GRAPH_DATA__</script>
<script>
'use strict';
const initialData=JSON.parse(document.getElementById('graphData').textContent);
const blueprint=document.getElementById('app').innerHTML;
let parentOrigin='*',lastRender='',ui={selected:'',draft:null,pending:null,linkSource:'',connecting:false,view:null,lastAck:''};
function post(type,values){window.parent.postMessage(Object.assign({isStreamlitMessage:true,type:type},values||{}),parentOrigin);}
function mount(data,ack){
document.getElementById('app').innerHTML=blueprint;
document.getElementById('app').classList.toggle('editor',!!data.editable);
if(ack&&ack.id!==ui.lastAck&&(!ui.pending||ack.id===ui.pending.action_id)){if(ack.ok){ui.draft=null;ui.selected=ack.selected||ui.selected;ui.connecting=false;ui.linkSource='';}ui.pending=null;ui.lastAck=ack.id;}
const byId=new Map(data.nodes.map(n=>[n.entity_id,n]));
const NS='http://www.w3.org/2000/svg', $=id=>document.getElementById(id);
const canvas=$('canvas'), viewport=$('viewport'), panel=$('detail');
let selected='',labels=false,zoom=1,tx=0,ty=0,drag=null,edgeElements=[],nodeElements=new Map(),connectionDrag=null;
function element(tag,attrs,parent){const el=document.createElementNS(NS,tag);Object.entries(attrs||{}).forEach(([k,v])=>el.setAttribute(k,v));if(parent)parent.appendChild(el);return el;}
function text(parent,value,attrs){const el=element('text',attrs,parent);el.textContent=value;return el;}
function html(tag,value,parent,className){const el=document.createElement(tag);if(value!==undefined)el.textContent=value;if(className)el.className=className;if(parent)parent.appendChild(el);return el;}
function initials(name){return name.trim().split(/\s+/).slice(0,2).map(s=>s[0]||'').join('').toUpperCase();}
function shorten(s,n){s=String(s||'');return s.length>n?s.slice(0,n-1)+'…':s;}
function wrap(s,length,limit){let out=[],line='';String(s||'').split(/\s+/).forEach(word=>{if((line+' '+word).trim().length>length&&line){out.push(line);line=word;}else{line=(line+' '+word).trim();}});if(line)out.push(line);if(out.length>limit){out=out.slice(0,limit);out[limit-1]=shorten(out[limit-1],length-1)+'…';}return out.map(v=>shorten(v,length));}
function radius(n){return data.mode==='organigrama'?42:n.entity_type==='PERSONA'?34:24;}
function transform(){viewport.setAttribute('transform','translate('+tx+' '+ty+') scale('+zoom+')');ui.view={zoom,tx,ty};}
function fit(){zoom=1;tx=0;ty=0;transform();}
function closePanel(){selected='';ui.selected='';ui.draft=null;panel.classList.add('hidden');highlight();}
function field(parent,key,value){if(!value)return;html('dt',key,parent);html('dd',String(value),parent);}
function highlight(){const neighbours=new Set([selected]);data.edges.forEach(r=>{if(r.source_id===selected)neighbours.add(r.target_id);if(r.target_id===selected)neighbours.add(r.source_id);});
 nodeElements.forEach((g,id)=>{g.classList.toggle('selected',id===selected);g.classList.toggle('muted',!!selected&&!neighbours.has(id));});
 edgeElements.forEach(e=>e.g.classList.toggle('muted',!!selected&&e.r.source_id!==selected&&e.r.target_id!==selected));}
function detail(id){const n=byId.get(id);if(!n)return;selected=id;ui.selected=id;ui.draft=null;panel.replaceChildren();panel.classList.remove('hidden');
 const close=html('button','Cerrar ×',panel,'light');close.style.float='right';close.onclick=closePanel;
 if(n.photo){const photo=html('img',undefined,panel,'portrait');photo.src=n.photo;photo.alt='Fotografía registrada de '+n.label;}else{html('div',initials(n.label),panel,'portrait initials');}
 html('h2',n.label,panel);if(n.alias)html('p','Alias: '+n.alias,panel,'muted-text');
 if(data.editable){const edit=html('button','Editar ficha',panel,'primary');edit.onclick=()=>actorForm(n.entity_type,null,n);const link=html('button','Conectar',panel,'light');link.onclick=()=>startConnect(id);}
 html('span',n.entity_type,panel,'badge');html('span',n.confidence||'PENDIENTE',panel,'badge'+(n.confidence==='CONFIRMADO'?'':' pending'));
 const dl=html('dl',undefined,panel);Object.entries(n.fields).forEach(([k,v])=>field(dl,k,v));
 field(dl,'Origen',n.source_type);field(dl,'Fuente de la ficha',n.source_detail);field(dl,'ID de entidad',n.entity_id);
 if(n.notes){html('h3','Observaciones',panel);html('p',n.notes,panel);}
 html('h3','Relaciones registradas · '+n.links.length,panel);
 if(!n.links.length)html('p','Sin vínculos registrados. Añádelos en la ficha editable o en Edición manual.',panel,'muted-text');
 n.links.forEach(l=>{const card=html('div',undefined,panel,'link-card');const btn=html('button',l.direction+' '+l.label,card);btn.onclick=()=>{if(byId.has(l.id))detail(l.id);else html('p','Entidad fuera de esta vista. Amplía los saltos o selecciónala en los filtros.',card,'muted-text');};
 html('p',l.relation.replaceAll('_',' ')+' · '+l.type,card);html('p',l.source_type+' · '+l.confidence+(l.status==='DESCARTADA'?' · DESCARTADA':''),card,'muted-text');
 if(l.description)html('p',l.description,card);html('p','Fuente: '+(l.source||l.source_detail||'No registrada'),card,'muted-text');
 if(l.start||l.end)html('p','Vigencia: '+(l.start||'Sin fecha')+' → '+(l.end||'Abierta'),card,'muted-text');
 html('p','Evidencias: '+(l.evidence_ids||'Sin evidencia vinculada'),card,'muted-text');});
 html('h3','Evidencias · '+n.evidence.length,panel);n.evidence.forEach(e=>{const card=html('div',undefined,panel,'link-card');html('strong',e.title,card);html('p',e.id+' · '+e.source,card,'muted-text');});
 html('p',data.editable?'Edita la ficha o conecta este actor con otro desde aquí.':'Vista de consulta. Abre el expediente en la aplicación para editar.',panel,'muted-text');highlight();}
function edgeDetail(r){panel.replaceChildren();panel.classList.remove('hidden');const close=html('button','Cerrar ×',panel,'light');close.onclick=closePanel;
 html('h2',r.relation_type.replaceAll('_',' '),panel);html('p',byId.get(r.source_id).label+' → '+byId.get(r.target_id).label,panel);
 const dl=html('dl',undefined,panel);[['Origen',r.source_type],['Confianza',r.confidence],['Fuente',r.source],['Detalle de fuente',r.source_detail],['Descripción',r.description],['Soporte CDR',r.support_count],['Evidencias',r.evidence_ids],['Desde',r.start_date],['Hasta',r.end_date],['Registros agrupados',r.records]].forEach(([k,v])=>field(dl,k,v));
 html('p','ID: '+r.relation_ids.join(', '),panel,'muted-text');
 if(data.editable&&r.source_type==='MANUAL'&&r.relation_ids.length===1){const discard=html('button','Descartar vínculo',panel,'danger');discard.onclick=()=>send('discard',{values:{relation_id:r.relation_ids[0]}});}}
function note(value,error){$('editorNote').textContent=value;$('editorNote').style.background=error?'#fff0ec':'#edf8f5';}
function currentPositions(){return Object.fromEntries(data.nodes.map(n=>[n.entity_id,[n.x,n.y]]));}
function send(operation,extra){if(!data.editable||ui.pending)return;
 const action_id=typeof crypto.randomUUID==='function'?crypto.randomUUID():Date.now()+'-'+Math.random().toString(36).slice(2);
 const event=Object.assign({action_id,operation,case_id:data.case_id,revision:data.revision,mode:data.mode,positions:currentPositions(),size:[data.width,data.height]},extra||{});
 ui.pending=event;document.querySelectorAll('#app button,#app input,#app select,#app textarea').forEach(el=>el.disabled=true);
 note('Guardando el cambio…');post('streamlit:setComponentValue',{value:event,dataType:'json'});}
function activateNode(id){if(ui.pending)return;if(data.editable&&ui.connecting){if(!ui.linkSource){startConnect(id);return;}if(id===ui.linkSource){note('Selecciona otro actor como destino.');return;}relationForm(ui.linkSource,id);ui.connecting=false;ui.linkSource='';return;}detail(id);}
function startConnect(id){ui.draft=null;ui.connecting=true;ui.linkSource=id||'';panel.classList.add('hidden');selected=id||'';highlight();note(id?'Origen: '+byId.get(id).label+'. Ahora pulsa el actor de destino.':'Pulsa el actor de origen y después el de destino.');}
const iconPaths={
 'PERSONA':'<circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/>',
 'TELEFONO':'<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M10 5h4M10 19h4"/>',
 'IMEI':'<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 1v3m4-3v3m4-3v3M8 20v3m4-3v3m4-3v3M1 8h3m-3 4h3m-3 4h3m16-8h3m-3 4h3m-3 4h3"/><rect x="8" y="8" width="8" height="8"/>',
 'IMSI/SIM':'<path d="M8 2h10v20H5V6z"/><rect x="8" y="10" width="7" height="8"/>',
 'PERFIL DIGITAL':'<circle cx="12" cy="12" r="10"/><ellipse cx="12" cy="12" rx="5" ry="10"/><path d="M2 12h20"/>',
 'CORREO ELECTRONICO':'<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m2 5 10 8L22 5"/>',
 'VEHICULO':'<path d="m4 10 3-6h10l3 6v10H4zM4 10h16M7 14h2m6 0h2M6 20v2m12-2v2"/>',
 'DOMICILIO':'<path d="m2 11 10-9 10 9M5 9v13h14V9M10 22v-8h4v8"/>',
 'EMPRESA':'<path d="M4 22V4l16-2v20zM8 7h2m4 0h2M8 11h2m4 0h2M8 15h2m4 0h2M10 22v-4h4v4"/>',
 'ANTENA':'<path d="m7 22 5-13 5 13M5 4a10 10 0 0 0 0 12M19 4a10 10 0 0 1 0 12M8 7a5 5 0 0 0 0 6m8-6a5 5 0 0 1 0 6"/><circle cx="12" cy="10" r="2"/>',
 'UBICACION':'<path d="M12 22S3 13 3 9a9 9 0 0 1 18 0c0 4-9 13-9 13z"/><circle cx="12" cy="9" r="3"/>',
 'EVIDENCIA':'<path d="M5 2h10l5 5v15H5zM15 2v6h5M8 12h9M8 16h9"/>',
 'EVENTO':'<circle cx="12" cy="12" r="10"/><path d="M12 5v7l5 3"/>',
 'CASO':'<path d="M2 6V3h8l3 3h9v15H2z"/>'};
function actorIcon(kind){return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'+(iconPaths[kind]||iconPaths.PERSONA)+'</svg>';}
function setupEditor(){const palette=$('palette');html('h3','Actores',palette);html('p','Arrastra un icono al lienzo o pulsa para añadir.',palette);
 data.actor_types.forEach(kind=>{const btn=html('button',undefined,palette,'actor-tool');btn.type='button';btn.draggable=true;btn.dataset.actor=kind;btn.title='Añadir '+kind.toLocaleLowerCase('es');btn.setAttribute('aria-label','Añadir '+kind);
 const icon=html('span',undefined,btn);icon.innerHTML=actorIcon(kind);html('span',kind.toLocaleLowerCase('es'),btn);
 if(data.mode==='organigrama'&&kind!=='PERSONA'){btn.disabled=true;btn.title='Disponible en Red de vínculos';}
 btn.addEventListener('dragstart',ev=>{if(ui.pending){ev.preventDefault();return;}ev.dataTransfer.setData('text/plain',kind);ev.dataTransfer.effectAllowed='copy';});
 btn.onclick=()=>{if(ui.pending)return;actorForm(kind,[Math.max(50,(data.width/2-tx)/zoom),Math.max(50,(data.height/2-ty)/zoom)]);};});
 if(data.mode==='organigrama')html('p','Personas, empresas y otros actores juntos: usa Red de vínculos.',palette);
 canvas.addEventListener('dragover',ev=>{if(!ui.pending){ev.preventDefault();ev.dataTransfer.dropEffect='copy';}});
 canvas.addEventListener('drop',ev=>{ev.preventDefault();if(ui.pending)return;const kind=ev.dataTransfer.getData('text/plain');if(!data.actor_types.includes(kind))return;
 if(data.mode==='organigrama'&&kind!=='PERSONA'){note('Añade empresas y otros actores en Red de vínculos.',true);return;}const p=point(ev);actorForm(kind,[Math.max(50,(p.x-tx)/zoom),Math.max(50,(p.y-ty)/zoom)]);});
 $('connect').onclick=()=>startConnect(selected);$('arrange').onclick=()=>{ui.view=null;ui.selected='';send('arrange',{});};
 note('1. Arrastra un actor · 2. Completa su ficha · 3. Conecta dos actores. Los cambios se guardan en el expediente de esta sesión.');
 if(!data.nodes.length){text(viewport,'Arrastra aquí una persona, empresa u otro actor',{id:'emptyHelp',x:data.width/2,y:data.height/2,'text-anchor':'middle'});}
}
function formInput(parent,label,name,value,kind){const id='editor-'+name.replaceAll('.','-');const caption=html('label',label,parent);caption.htmlFor=id;
 const el=html(kind==='textarea'?'textarea':'input',undefined,parent);el.id=id;el.name=name;if(kind!=='textarea')el.type=kind||'text';if(value!==undefined&&value!==null)el.value=value;return el;}
function formSelect(parent,label,name,options,value,multiple){const caption=html('label',label,parent);caption.htmlFor='editor-'+name;
 const el=html('select',undefined,parent);el.id='editor-'+name;el.name=name;el.multiple=!!multiple;
 options.forEach(option=>{const key=typeof option==='string'?option:option[0],title=typeof option==='string'?option:option[1];const opt=html('option',title,el);opt.value=key;opt.selected=multiple?(value||[]).includes(key):value===key;});return el;}
function evidenceSelect(form,selectedIds){const options=new Map((data.evidence_options||[]).map(e=>[e.id,e.title+' · '+e.id]));
 (selectedIds||[]).forEach(id=>{if(!options.has(id))options.set(id,id);});return formSelect(form,'Evidencias vinculadas (opcional)','evidence_ids',[...options],selectedIds||[],true);}
function actorForm(kind,dropPoint,existing,seed){if(ui.pending)return;
 const initial=seed||{label:existing?existing.label:'',source:existing?existing.source_detail:'Captura manual',confidence:existing?existing.confidence:'PENDIENTE',
 notes:existing?existing.notes:'',evidence_ids:existing?existing.own_evidence_ids:[],metadata:Object.assign({},existing?existing.metadata:{},{visual_color:existing?existing.visual_color:'#216e7a',visual_shape:existing?existing.visual_shape:'circle',visual_group:existing?existing.visual_group:''}),photo_data:'',photo_name:'',photo_source:''};
 ui.draft={kind:'actor',type:kind,id:existing?existing.entity_id:'',point:dropPoint,values:initial};ui.connecting=false;ui.linkSource='';
 panel.replaceChildren();panel.classList.remove('hidden');const close=html('button','Cancelar',panel,'light');close.onclick=closePanel;
 html('h2',existing?'Editar actor':'Nuevo actor',panel);html('p',kind.replaceAll('_',' '),panel,'muted-text');
 const form=html('form',undefined,panel);form.id='actorForm';
 const name=formInput(form,kind==='PERSONA'?'Nombre completo':'Nombre / identificador','label',initial.label);name.required=true;name.maxLength=500;
 if(existing&&['TELEFONO','IMEI','IMSI/SIM','CORREO ELECTRONICO','ANTENA'].includes(kind))name.readOnly=true;
 const alias=formInput(form,'Alias / referencia','metadata.alias',(initial.metadata||{}).alias||'');
 const role=formInput(form,'Cargo / función','metadata.role',(initial.metadata||{}).role||'');
 const more=html('details',undefined,form);html('summary','Más datos de la ficha',more);
 data.profile_fields.filter(([key])=>!['alias','role'].includes(key)).forEach(([key,label])=>formInput(more,label,'metadata.'+key,(initial.metadata||{})[key]||'',key==='other_details'?'textarea':'text'));
 formInput(form,'Grupo visual (opcional)','metadata.visual_group',(initial.metadata||{}).visual_group||'');
 formInput(form,'Color del actor','metadata.visual_color',(initial.metadata||{}).visual_color||'#216e7a','color');
 formSelect(form,'Forma','metadata.visual_shape',[['circle','Círculo'],['hexagon','Hexágono']],(initial.metadata||{}).visual_shape||'circle');
 const source=formInput(form,'Fuente / referencia','source',initial.source||'Captura manual');source.required=true;
 const confidence=formSelect(form,'Confianza','confidence',data.confidence_levels,initial.confidence||'PENDIENTE');
 if(existing&&kind!=='PERSONA'&&existing.source_type!=='MANUAL'){source.readOnly=true;confidence.disabled=true;}
 formInput(form,'Observaciones','notes',initial.notes||'','textarea');evidenceSelect(form,initial.evidence_ids);
 let photoData=initial.photo_data||'',photoName=initial.photo_name||'',readingPhoto=false;
 {
 const photo=formInput(form,kind==='PERSONA'?'Fotografía (hasta 5 MB)':'Imagen / logotipo (hasta 5 MB)','photo_file','','file');photo.accept='image/png,image/jpeg,image/webp';
 const fileNote=html('p',photoName||(existing&&existing.photo?'Fotografía actual conservada.':'Fotografía opcional.'),form,'muted-text');
 formInput(form,'Fuente de la fotografía','photo_source',initial.photo_source||'');
 photo.onchange=()=>{const file=photo.files[0];if(!file)return;if(file.size>5*1024*1024){note('La fotografía supera 5 MB.',true);photo.value='';return;}
 readingPhoto=true;fileNote.textContent='Leyendo fotografía…';const reader=new FileReader();reader.onload=()=>{readingPhoto=false;photoData=reader.result;photoName=file.name;fileNote.textContent=file.name;remember();};reader.onerror=()=>{readingPhoto=false;note('No se pudo leer la fotografía.',true);};reader.readAsDataURL(file);};
 if(existing&&existing.photo){const label=html('label',undefined,form);const remove=html('input',undefined,label);remove.type='checkbox';remove.name='remove_photo';remove.checked=!!initial.remove_photo;label.appendChild(document.createTextNode(' Retirar fotografía actual'));}
 }
 const submit=html('button',existing?'Guardar cambios':'Crear actor',form,'primary');submit.type='submit';
 function collect(){const fd=new FormData(form),metadata={};for(const [key,value] of fd.entries())if(key.startsWith('metadata.'))metadata[key.slice(9)]=String(value);
 return {entity_type:kind,label:String(fd.get('label')||''),source:String(fd.get('source')||'Captura manual'),confidence:String(fd.get('confidence')||initial.confidence||'PENDIENTE'),notes:String(fd.get('notes')||''),metadata,evidence_ids:fd.getAll('evidence_ids'),photo_data:photoData,photo_name:photoName,photo_source:String(fd.get('photo_source')||fd.get('source')||'Captura manual'),remove_photo:fd.get('remove_photo')==='on'};}
 function remember(){if(ui.draft&&ui.draft.kind==='actor')ui.draft.values=collect();}
 form.oninput=remember;form.onchange=remember;
 form.onsubmit=ev=>{ev.preventDefault();if(readingPhoto){note('Espera a que termine de leer la fotografía.',true);return;}remember();send(existing?'edit':'create',{entity_id:existing?existing.entity_id:'',point:dropPoint,values:collect()});};
 note(existing?'Edita los valores y pulsa Guardar cambios.':'Completa el nombre y pulsa Crear actor. El actor aparecerá donde lo soltaste.');
 name.focus();
}
function relationForm(sourceId,targetId,seed){if(ui.pending)return;const a=byId.get(sourceId),b=byId.get(targetId);if(!a||!b||sourceId===targetId)return;
 const people=a.entity_type==='PERSONA'&&b.entity_type==='PERSONA';
 const types=data.relation_types.filter(kind=>people||!data.personal_types.includes(kind)&&!data.hierarchy_types.includes(kind));
 const defaultKind=data.mode==='organigrama'?'DIRIGE_A':a.entity_type==='PERSONA'&&b.entity_type==='TELEFONO'?'UTILIZA':'RELACION_DOCUMENTAL';
 const initial=seed||{relation_type:defaultKind,source:'Captura manual',confidence:'PENDIENTE',description:'',evidence_ids:[],visual_color:'#d65761'};
 ui.draft={kind:'relation',source:sourceId,target:targetId,values:initial};ui.connecting=false;ui.linkSource='';panel.replaceChildren();panel.classList.remove('hidden');
 const cancel=html('button','Cancelar',panel,'light');cancel.onclick=closePanel;html('h2','Nuevo vínculo',panel);html('p',a.label+' → '+b.label,panel);
 if(people)html('p','Para crear una jerarquía elige Dirige a o Supervisa a. La flecha saldrá del superior hacia el dependiente.',panel,'muted-text');
 const form=html('form',undefined,panel);form.id='relationForm';
 formSelect(form,'Tipo de vínculo','relation_type',types.map(kind=>[kind,kind.replaceAll('_',' ').toLocaleLowerCase('es')]),initial.relation_type);
 formInput(form,'Fuente / referencia','source',initial.source||'Captura manual').required=true;
 formSelect(form,'Confianza','confidence',data.confidence_levels,initial.confidence||'PENDIENTE');
 formInput(form,'Color del vínculo','visual_color',initial.visual_color||'#d65761','color');
 formInput(form,'Descripción del vínculo','description',initial.description||'','textarea');evidenceSelect(form,initial.evidence_ids||[]);
 const submit=html('button','Guardar vínculo',form,'primary');submit.type='submit';
 function collect(){const fd=new FormData(form);return {source_id:sourceId,target_id:targetId,relation_type:fd.get('relation_type'),source:fd.get('source'),confidence:fd.get('confidence'),description:fd.get('description'),visual_color:fd.get('visual_color'),evidence_ids:fd.getAll('evidence_ids')};}
 form.oninput=()=>{if(ui.draft)ui.draft.values=collect();};form.onchange=form.oninput;
 form.onsubmit=ev=>{ev.preventDefault();ui.draft.values=collect();send('connect',{values:collect()});};
 note('Define la relación entre los dos actores y guarda el vínculo.');
}
function drawEdges(){edgeElements.forEach(e=>{const a=byId.get(e.r.source_id),b=byId.get(e.r.target_id),dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1;
 const org=data.mode==='organigrama';let x1=a.x+dx/len*(radius(a)+4),y1=a.y+dy/len*(radius(a)+4),x2=b.x-dx/len*(radius(b)+9),y2=b.y-dy/len*(radius(b)+9);
 let d='M'+x1+','+y1+' L'+x2+','+y2;
 if(org&&Math.abs(dy)>100){const downward=dy>0;y1=a.y+(downward?133:-radius(a)-5);x1=a.x;x2=b.x;y2=b.y+(downward?-radius(b)-10:133);const mid=(y1+y2)/2;d='M'+x1+','+y1+' V'+mid+' H'+x2+' V'+y2;}
 e.path.setAttribute('d',d);e.hit.setAttribute('d',d);e.label.setAttribute('x',(x1+x2)/2);e.label.setAttribute('y',(y1+y2)/2-7);});}
function build(){canvas.setAttribute('viewBox','0 0 '+data.width+' '+data.height);
 data.edges.forEach(r=>{if(!byId.has(r.source_id)||!byId.has(r.target_id))return;const g=element('g',{'class':'edge'},$('edges'));
 const inferred=r.source_type==='INFERIDO'||r.confidence==='INFERIDO',manual=r.source_type==='MANUAL';
 const color=inferred?'#cc922b':r.visual_color||(manual?'#d65761':'#7eaacb');
 const markerId='edgeArrow'+color.slice(1);if(!$(markerId)){const marker=element('marker',{id:markerId,markerWidth:9,markerHeight:9,refX:8,refY:4.5,orient:'auto-start-reverse',markerUnits:'userSpaceOnUse'},$('defs'));element('path',{d:'M0,0 L9,4.5 L0,9',fill:color},marker);}
 const uncertain=['PROBABLE','PENDIENTE','INFERIDO'].includes(r.confidence);
 const path=element('path',{fill:'none',stroke:color,'stroke-width':data.mode==='organigrama'?2.8:1.3+Math.min(4,Math.log2(1+Number(r.support_count||0))*.7),'stroke-dasharray':inferred?'7 5':uncertain?'3 4':'','marker-end':'url(#'+markerId+')',opacity:manual?.83:.62},g);
 const hit=element('path',{fill:'none',stroke:'transparent','stroke-width':14},g);
 const label=text(g,r.relation_type.replaceAll('_',' '),{'class':'edge-label','text-anchor':'middle',display:'none'});
 g.addEventListener('click',ev=>{if(drag&&drag.moved)return;ev.stopPropagation();edgeDetail(r);});edgeElements.push({r,g,path,hit,label});});
 data.nodes.forEach((n,index)=>{const r=radius(n),g=element('g',{'class':'node',transform:'translate('+n.x+' '+n.y+')',tabindex:0,role:'button','aria-label':n.label+', abrir ficha','data-id':n.entity_id},$('nodes'));nodeElements.set(n.entity_id,g);
 element('circle',{r:r+7,fill:'#fff',stroke:'#dfe9ee','stroke-width':1.5,'class':'halo'},g);
 const hex=n.visual_shape==='hexagon';const hexPoints=Array.from({length:6},(_,i)=>{const angle=Math.PI/3*i;return Math.cos(angle)*r+','+Math.sin(angle)*r;}).join(' ');
 element(hex?'polygon':'circle',Object.assign(hex?{points:hexPoints}:{r},{fill:n.entity_type==='PERSONA'?'#e7f1f1':n.color+'18',stroke:n.visual_color||n.color,'stroke-width':3}),g);
 if(n.photo){const clip=element('clipPath',{id:'photo'+index},$('defs'));element(hex?'polygon':'circle',hex?{points:hexPoints,transform:'scale(.93)'}:{r:r-2},clip);element('image',{x:-r+2,y:-r+2,width:(r-2)*2,height:(r-2)*2,href:n.photo,preserveAspectRatio:'xMidYMid slice','clip-path':'url(#photo'+index+')'},g);}
 else if(n.entity_type==='PERSONA'){text(g,initials(n.label),{y:7,'text-anchor':'middle','font-size':22,fill:'#236166','font-family':'Arial,sans-serif','font-weight':600});}
 else{const icon=element('svg',{x:-14,y:-14,width:28,height:28,viewBox:'0 0 24 24',fill:'none',stroke:n.visual_color||n.color,'stroke-width':1.6,'stroke-linecap':'round','stroke-linejoin':'round'},g);icon.innerHTML=iconPaths[n.entity_type]||iconPaths.CASO;}
 const lines=wrap(n.label,data.mode==='organigrama'?25:22,2);lines.forEach((line,i)=>text(g,line,{y:r+24+i*16,'text-anchor':'middle','class':data.mode==='organigrama'?'label org':'label'}));
 const description=data.mode==='organigrama'?[n.role,n.organization].filter(Boolean).join(' · '):n.visual_group||n.alias||n.role||n.entity_type;
 wrap(description,28,data.mode==='organigrama'?2:1).forEach((line,i)=>text(g,line,{y:r+28+lines.length*16+i*14,'text-anchor':'middle','class':data.mode==='organigrama'?'sub org':'sub'}));
 const title=element('title',{},g);title.textContent=n.label+(n.role?' · '+n.role:'');
 if(data.editable){const port=element('circle',{cx:r+12,cy:0,r:6,'class':'connect-port',role:'button','aria-label':'Conectar desde '+n.label},g);port.addEventListener('pointerdown',ev=>{if(ui.pending)return;ev.preventDefault();ev.stopPropagation();connectionDrag={id:n.entity_id,path:element('path',{d:'',fill:'none',stroke:'#14978c','stroke-width':2,'stroke-dasharray':'6 4'},viewport)};canvas.setPointerCapture(ev.pointerId);});}
 g.addEventListener('pointerdown',ev=>{if(ev.button!==0||ui.pending)return;ev.stopPropagation();const p=point(ev);drag={node:n,start:p,x:n.x,y:n.y,screenX:ev.clientX,screenY:ev.clientY,moved:false};canvas.setPointerCapture(ev.pointerId);});
 g.addEventListener('click',ev=>ev.stopPropagation());
 g.addEventListener('keydown',ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();activateNode(n.entity_id);}});});
 drawEdges();}
function point(ev){const p=new DOMPoint(ev.clientX,ev.clientY);return p.matrixTransform(canvas.getScreenCTM().inverse());}
canvas.addEventListener('pointerdown',ev=>{if(ev.button!==0||ui.pending)return;const p=point(ev);drag={start:p,x:tx,y:ty,screenX:ev.clientX,screenY:ev.clientY,moved:false};canvas.setPointerCapture(ev.pointerId);});
canvas.addEventListener('pointermove',ev=>{const p=point(ev);if(connectionDrag){const n=byId.get(connectionDrag.id);connectionDrag.path.setAttribute('d','M'+n.x+','+n.y+' L'+((p.x-tx)/zoom)+','+((p.y-ty)/zoom));return;}if(!drag)return;if(Math.hypot(ev.clientX-drag.screenX,ev.clientY-drag.screenY)>3)drag.moved=true;
 if(drag.node){drag.node.x=Math.max(50,drag.x+(p.x-drag.start.x)/zoom);drag.node.y=Math.max(50,drag.y+(p.y-drag.start.y)/zoom);nodeElements.get(drag.node.entity_id).setAttribute('transform','translate('+drag.node.x+' '+drag.node.y+')');drawEdges();}
 else{tx=drag.x+p.x-drag.start.x;ty=drag.y+p.y-drag.start.y;transform();}});
canvas.addEventListener('pointerup',ev=>{if(connectionDrag){const p=point(ev),x=(p.x-tx)/zoom,y=(p.y-ty)/zoom;const target=data.nodes.find(n=>n.entity_id!==connectionDrag.id&&Math.hypot(n.x-x,n.y-y)<radius(n)+24);const source=connectionDrag.id;connectionDrag.path.remove();connectionDrag=null;if(target)relationForm(source,target.entity_id);else note('Suelta el conector sobre otro actor.');}
 else if(drag&&drag.node){if(!drag.moved)activateNode(drag.node.entity_id);else if(data.editable)send('move',{});}if(canvas.hasPointerCapture(ev.pointerId))canvas.releasePointerCapture(ev.pointerId);drag=null;});
canvas.addEventListener('pointercancel',()=>{drag=null;if(connectionDrag)connectionDrag.path.remove();connectionDrag=null;});
function zoomAt(factor,p){const next=Math.max(.2,Math.min(8,zoom*factor));tx=p.x-(p.x-tx)*next/zoom;ty=p.y-(p.y-ty)*next/zoom;zoom=next;transform();}
canvas.addEventListener('wheel',ev=>{ev.preventDefault();zoomAt(ev.deltaY<0?1.12:1/1.12,point(ev));},{passive:false});
$('zoomIn').onclick=()=>zoomAt(1.25,{x:data.width/2,y:data.height/2});$('zoomOut').onclick=()=>zoomAt(.8,{x:data.width/2,y:data.height/2});
$('fit').onclick=()=>{fit();closePanel();$('search').value='';};
$('labels').onclick=()=>{labels=!labels;$('labels').setAttribute('aria-pressed',String(labels));edgeElements.forEach(e=>e.label.setAttribute('display',labels?'block':'none'));};
$('search').addEventListener('input',ev=>{const query=ev.target.value.trim().toLocaleLowerCase('es');if(!query){closePanel();return;}
 const n=data.nodes.find(n=>(n.label+' '+n.alias+' '+n.entity_id).toLocaleLowerCase('es').includes(query));if(n)detail(n.entity_id);});
$('export').onclick=()=>{const svg=canvas.cloneNode(true);svg.setAttribute('width',data.width);svg.setAttribute('height',data.height);
 const style=element('style',{});style.textContent=document.querySelector('style').textContent;svg.insertBefore(style,svg.firstChild);
 const bg=element('rect',{width:'100%',height:'100%',fill:'#fbfdfe'});svg.insertBefore(bg,svg.querySelector('#viewport'));
 const blob=new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml;charset=utf-8'});const url=URL.createObjectURL(blob);
 const a=document.createElement('a');a.href=url;a.download='sentinel-'+data.mode+'.svg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('viewTitle').textContent=(data.mode==='organigrama'?'Organigrama':'Red de vínculos')+' / '+data.case_name;
$('count').textContent=data.nodes.length+' entidades · '+data.edges.length+' vínculos';
if(data.messages.length){$('message').textContent=data.messages.join(' ');$('message').style.display='block';}
build();if(ui.view){zoom=ui.view.zoom;tx=ui.view.tx;ty=ui.view.ty;transform();}
if(data.editable){setupEditor();if(ui.draft){if(ui.draft.kind==='actor')actorForm(ui.draft.type,ui.draft.point,byId.get(ui.draft.id),ui.draft.values);else relationForm(ui.draft.source,ui.draft.target,ui.draft.values);}else if(byId.has(ui.selected))detail(ui.selected);if(ack)note(ack.message,!ack.ok);}
else if(data.focus&&byId.has(data.focus))detail(data.focus);
document.onkeydown=ev=>{if(ev.key==='Escape'){ui.connecting=false;ui.linkSource='';closePanel();if(data.editable)note('Arrastra un actor al lienzo, completa su ficha y conéctalo.');}};
}
if(initialData){mount(initialData,null);}else{
window.addEventListener('message',event=>{if(event.source!==window.parent||!event.data||event.data.type!=='streamlit:render')return;parentOrigin=event.origin;const args=event.data.args||{};if(!args.payload)return;const signature=JSON.stringify([args.payload,args.ack]);if(signature===lastRender)return;lastRender=signature;mount(args.payload,args.ack);post('streamlit:setFrameHeight',{height:820});});
post('streamlit:componentReady',{apiVersion:1});post('streamlit:setFrameHeight',{height:820});}
</script></body></html>'''


def identity_html(entities: pd.DataFrame, relations: pd.DataFrame, *, focus: str = "", height: int = 680,
                  state: dict | None = None, compare: str = "", mode: str = "red") -> str:
    if entities.empty:
        return '<div style="padding:3rem;text-align:center;color:#64748b;background:#f8fafc;border:1px solid #dbe5ed;border-radius:18px;font:14px Arial">Sin entidades en esta vista. Crea una ficha o ajusta los filtros.</div>'
    payload = diagram_payload(state or {"entities": entities.to_dict("records"), "relationships": relations.to_dict("records")},
                              entities, relations, focus=focus, compare=compare, mode=mode)
    safe_json = json.dumps(payload, ensure_ascii=False, default=str).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return DIAGRAM_HTML.replace("__GRAPH_DATA__", safe_json)


def export_excel(state: dict) -> bytes:
    buf = BytesIO()
    raw = export_json(state)
    encoded = base64.b64encode(zlib.compress(raw)).decode("ascii")
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet, frame in state_frames(state).items():
            # Readable tables plus a lossless canonical snapshot for reimport.
            # Long fields remain in the snapshot, never silently truncated.
            frame = frame.map(lambda value: str(value) if not isinstance(value, (int, float, bool)) else value)
            frame = frame.map(lambda value: value if not isinstance(value, str) or len(value) < 32000 else "Contenido extenso conservado en PROYECTO_JSON")
            frame.to_excel(writer, index=False, sheet_name=sheet[:31])
        pd.DataFrame(state.get("imports", [])).to_excel(writer, index=False, sheet_name="IMPORTACIONES")
        pd.DataFrame([{"parte": i // 30000, "sha256": file_hash(raw), "contenido": encoded[i:i + 30000]}
                      for i in range(0, len(encoded), 30000)]).to_excel(writer, index=False, sheet_name="PROYECTO_JSON")
        pd.DataFrame([{k: asset.get(k, "") for k in ("asset_id", "file_name", "mime_type", "sha256", "source")}
                      for asset in state.get("assets", {}).values()],
                     columns=["asset_id", "file_name", "mime_type", "sha256", "source"]).to_excel(writer, index=False, sheet_name="FOTOGRAFIAS")
        # User supplied text must remain text, including identifiers beginning '='.
        for sheet in writer.book:
            for row in sheet:
                for cell in row:
                    if cell.data_type == "f":
                        cell.data_type = "s"
    return buf.getvalue()


def export_json(state: dict) -> bytes:
    return json.dumps({"identity_state": state, "version": APP_VERSION}, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def workbook(nodes, edges, evidence=None):
    """Compatibility export retained for older callers."""
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        nodes.to_excel(writer, index=False, sheet_name="NODOS")
        edges.to_excel(writer, index=False, sheet_name="ARISTAS")
        if evidence is not None:
            evidence.to_excel(writer, index=False, sheet_name="EVIDENCIA_ORIGINAL")
    return buf.getvalue()


def _entity_ids_by_type(state: dict, kind: str) -> list[str]:
    return [x["entity_id"] for x in state.get("entities", []) if x.get("entity_type") == kind]


def _labels(state: dict, ids: list[str]) -> list[str]:
    lookup = entity_lookup(state)
    return [lookup.get(i, {}).get("label", i) for i in ids]


def common_contacts(state: dict, target_ids: list[str], minimum_targets: int = 2) -> pd.DataFrame:
    """Contacts shared by at least N selected target lines; direction is ignored."""
    neighbours: dict[str, set[str]] = defaultdict(set)
    for rel in state.get("relationships", []):
        if rel.get("relation_type") != "COMUNICACION" or rel.get("status") == "DESCARTADA":
            continue
        neighbours[rel.get("source_id", "")].add(rel.get("target_id", ""))
        neighbours[rel.get("target_id", "")].add(rel.get("source_id", ""))
    counts = Counter()
    for target in target_ids:
        for neighbour in neighbours.get(target, set()):
            if neighbour not in target_ids:
                counts[neighbour] += 1
    lookup = entity_lookup(state)
    rows = []
    for contact, count in counts.most_common():
        if count >= minimum_targets:
            rows.append({"contacto_id": contact, "contacto": lookup.get(contact, {}).get("label", contact), "targets": count, "cobertura": f"{count}/{len(target_ids)}"})
    return pd.DataFrame(rows, columns=["contacto_id", "contacto", "targets", "cobertura"])


def analysis_tables(state: dict, target_ids: list[str]) -> dict[str, pd.DataFrame]:
    lookup = entity_lookup(state)
    communication = [r for r in state.get("relationships", []) if r.get("relation_type") == "COMUNICACION" and r.get("status") != "DESCARTADA"]
    target_set = set(target_ids)
    target_lines = []
    target_target = []
    individual = []
    for rel in communication:
        src, dst = rel.get("source_id"), rel.get("target_id")
        src_label, dst_label = lookup.get(src, {}).get("label", src), lookup.get(dst, {}).get("label", dst)
        row = {"origen": src_label, "destino": dst_label, "eventos": rel.get("support_count", 0), "confidence": rel.get("confidence", "")}
        if src in target_set or dst in target_set:
            target_lines.append(row)
        if src in target_set and dst in target_set:
            target_target.append(row)
        if src in target_set or dst in target_set:
            individual.append(row)
    shared = []
    events = state.get("events", [])
    for attr in ("imei", "imsi", "antenna"):
        holders: dict[str, set[str]] = defaultdict(set)
        for event in events:
            value = text_value(event.get(attr))
            if value and event.get("source_id"):
                holders[value].add(event.get("source_id"))
        for value, lines in holders.items():
            if len(lines) > 1:
                shared.append({"atributo": attr.upper(), "valor": value, "lineas": ", ".join(_labels(state, list(lines))), "cantidad": len(lines), "observacion": "Coincidencia observada; no prueba identidad común."})
    location_holders: dict[str, set[str]] = defaultdict(set)
    for event in events:
        lat, lon = text_value(event.get("latitude")), text_value(event.get("longitude"))
        if lat and lon and event.get("source_id"):
            location_holders[f"{lat},{lon}"].add(event.get("source_id"))
    for value, lines in location_holders.items():
        if len(lines) > 1:
            shared.append({"atributo": "UBICACION", "valor": value, "lineas": ", ".join(_labels(state, list(lines))), "cantidad": len(lines), "observacion": "Coincidencia geográfica observada; no prueba convivencia."})
    # Temporal/geographic coincidences are presented as leads, never as inferred relations.
    coincidence_rows = []
    candidates = [e for e in events if e.get("source_id") in target_set and _event_datetime(e) is not None]
    for idx, first in enumerate(candidates[:2000]):
        first_dt = _event_datetime(first)
        for second in candidates[idx + 1:2000]:
            if first.get("source_id") == second.get("source_id"):
                continue
            second_dt = _event_datetime(second)
            delta = abs((first_dt - second_dt).total_seconds()) if first_dt and second_dt else 10**9
            if delta <= float(state.get("dedup_tolerance", 30)) * 10:
                same_geo = text_value(first.get("latitude")) and text_value(first.get("longitude")) and text_value(first.get("latitude")) == text_value(second.get("latitude")) and text_value(first.get("longitude")) == text_value(second.get("longitude"))
                coincidence_rows.append({"linea_a": lookup.get(first.get("source_id"), {}).get("label", first.get("source_id")), "linea_b": lookup.get(second.get("source_id"), {}).get("label", second.get("source_id")), "fecha_a": first.get("datetime", ""), "fecha_b": second.get("datetime", ""), "diferencia_s": int(delta), "misma_ubicacion": "Sí" if same_geo else "No", "observacion": "Pista temporal/geográfica; requiere corroboración independiente."})
                if len(coincidence_rows) >= 500:
                    break
        if len(coincidence_rows) >= 500:
            break
    personal = [r for r in state.get("relationships", []) if r.get("relation_type") in PERSONAL_RELATIONS or r.get("confidence") in {"PENDIENTE", "DESCARTADO"}]
    return {
        "lineas_objetivo": pd.DataFrame(target_lines), "objetivo_objetivo": pd.DataFrame(target_target),
        "contactos_individuales": pd.DataFrame(individual), "imeis_antenas": pd.DataFrame(shared),
        "relaciones_pendientes": frame_from_records(personal, RELATION_COLUMNS),
        "coincidencias": pd.DataFrame(coincidence_rows),
    }


def render_geo_svg(state: dict, *, entity_filter: list[str] | None = None, limit: int = 500) -> str:
    locations = []
    lookup = entity_lookup(state)
    selected = set(entity_filter or [])
    geo_types = {"ANTENA", "DOMICILIO", "EMPRESA", "UBICACION"}
    for entity in state.get("entities", []):
        if entity.get("entity_type") not in geo_types or (selected and entity["entity_id"] not in selected):
            continue
        try:
            meta = json.loads(entity.get("metadata", "{}"))
            lat, lon = float(meta.get("latitude")), float(meta.get("longitude"))
            locations.append((entity, lat, lon))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    locations = locations[:max(1, limit)]
    if not locations:
        return '<div style="padding:3rem;text-align:center;border:1px dashed #b7c7d8;border-radius:18px;color:#64748b">No hay coordenadas locales disponibles. El CDR no se envía a servicios externos.</div>'
    lats, lons = [x[1] for x in locations], [x[2] for x in locations]
    min_lat, max_lat, min_lon, max_lon = min(lats), max(lats), min(lons), max(lons)
    def px(lon: float) -> float:
        return 50 + 1020 * ((lon - min_lon) / (max_lon - min_lon or 1))
    def py(lat: float) -> float:
        return 520 - 430 * ((lat - min_lat) / (max_lat - min_lat or 1))
    marks = []
    for entity, lat, lon in locations:
        marks.append(f'<circle cx="{px(lon):.1f}" cy="{py(lat):.1f}" r="7" fill="#0ea5a4" stroke="#fff" stroke-width="2"><title>{escape(entity.get("label", ""))} · {lat:.5f}, {lon:.5f}</title></circle>')
    grid = "".join(f'<line x1="50" y1="{y}" x2="1070" y2="{y}" stroke="#dbe5ef"/>' for y in (90, 200, 310, 420, 520))
    return f'<div style="height:580px;border:1px solid #d8e3ef;border-radius:18px;background:#f8fbfe;overflow:hidden"><svg viewBox="0 0 1120 580" width="100%" height="100%"><rect width="1120" height="580" fill="#f8fbfe"/>{grid}<rect x="50" y="70" width="1020" height="450" fill="none" stroke="#b7c7d8" stroke-dasharray="4 5"/>{"".join(marks)}<text x="58" y="38" font-size="14" fill="#475569">Mapa local · {len(locations)} ubicaciones (máx. {limit})</text></svg></div>'


def add_manual_entity_to_state(state: dict, entity_type: str, label: str, confidence: str, notes: str, source_detail: str, metadata: dict | None = None) -> str:
    entity = add_entity(state, entity_type, label, source_type="MANUAL", source_detail=source_detail or "Alta manual", confidence=confidence, notes=notes, metadata=metadata)
    append_audit(state, "ALTA_ENTIDAD_MANUAL", f"{entity_type}: {label}", object_id=entity)
    return entity


def add_manual_relation_to_state(state: dict, source_id: str, target_id: str, relation_type: str, *, start_date: str = "", end_date: str = "", source: str = "", description: str = "", confidence: str = "PENDIENTE", notes: str = "", evidence_ids: list[str] | None = None, source_detail: str = "") -> str:
    relation = make_relation(state, source_id, target_id, relation_type, start_date=start_date, end_date=end_date, source=source, description=description, confidence=confidence, source_type="MANUAL", source_detail=source_detail or "Relación manual", notes=notes, evidence_ids=evidence_ids)
    if relation:
        append_audit(state, "ALTA_RELACION_MANUAL", f"{relation_type}: {source_id} → {target_id}", object_id=relation)
    return relation


def add_manual_evidence_to_state(state: dict, title: str, source: str, description: str, raw_json: str = "") -> str:
    eid = short_id("EVD")
    state["evidences"].append({"evidence_id": eid, "evidence_type": "MANUAL", "title": title, "source": source, "file_name": "", "sheet_name": "", "row_number": "", "source_hash": "", "captured_at": now_local(), "created_by": user_name(), "description": description, "raw_json": raw_json})
    append_audit(state, "ALTA_EVIDENCIA_MANUAL", title, object_id=eid)
    return eid


def _options_with_label(state: dict, *, types: tuple[str, ...] | None = None) -> tuple[list[str], dict[str, str]]:
    items = [x for x in state.get("entities", []) if not types or x.get("entity_type") in types]
    ids = [x["entity_id"] for x in items]
    counts = Counter(text_value(x.get("label")) for x in items)
    return ids, {x["entity_id"]: f"{ENTITY_ICONS.get(x.get('entity_type'), '•')} {x.get('label', x['entity_id'])}" + (f" · {x['entity_id'][-6:]}" if counts[text_value(x.get("label"))] > 1 else "") for x in items}


def _select_column(label: str, columns: list[str], preferred: str, key: str, optional: bool = False) -> str:
    options = (["(ninguna)"] if optional else []) + columns
    selected = preferred if preferred in options else ("(ninguna)" if optional else (columns[0] if columns else ""))
    choice = st.selectbox(label, options, index=options.index(selected) if selected in options else 0, key=key)
    return "" if choice == "(ninguna)" else choice


def render_case_loader() -> None:
    current = get_state()
    with st.expander("Cargar expediente o sustituir el mapa", expanded=current is None):
        mode = st.radio("Fuente de datos", ["CDR / Excel múltiple", "Expediente manual", "Proyecto de identidad", "Grafo legado"], horizontal=True, key="gm_load_mode")
        if mode == "Expediente manual":
            name = st.text_input("Nombre del expediente", value="Caso de identidades", key="gm_blank_case_name")
            st.caption("Comienza con personas y fotografías. Puedes registrar vínculos y jerarquías con su fuente y evidencia.")
            if current:
                st.info("Crear otro expediente sustituye el mapa de esta sesión. Descarga el proyecto actual para conservarlo.")
            if st.button("Crear expediente manual", type="primary", key="gm_blank_create"):
                set_state(new_state(name.strip() or "Caso de identidades"))
                st.rerun()
        elif mode == "CDR / Excel múltiple":
            uploads = st.file_uploader("Selecciona uno o varios CDR (Excel/CSV)", type=["xlsx", "xls", "xlsm", "csv"], accept_multiple_files=True, key="gm_cdr_uploads")
            if not uploads:
                st.caption("Se prioriza la hoja Datos_Limpios y se excluyen Duplicados, LOG y ESTADISTICAS.")
                return
            profiles: list[dict] = []
            configs: list[dict] = []
            for idx, upload in enumerate(uploads):
                try:
                    frame, sheet, digest, name = read_upload(upload)
                except Exception as error:
                    st.error(f"{getattr(upload, 'name', 'Archivo')}: {error}")
                    continue
                mapping = infer_mapping(frame)
                profiles.append({"frame": frame, "sheet_name": sheet, "source_hash": digest, "file_name": name, "import_id": short_id("IMP"), "captured_at": now_local()})
                # Streamlit no permite expanders anidados. El cargador completo
                # ya vive dentro de un expander; cada archivo usa un contenedor
                # delimitado para mantener el detalle multi-CDR sin romper la página.
                with st.container(border=True):
                    st.markdown(f"**{idx + 1}. {name}** · {len(frame):,} filas · hoja `{sheet}`")
                    st.dataframe(frame.head(4), use_container_width=True)
                    cols = [text_value(c) for c in frame.columns]
                    a, b, c = st.columns(3)
                    with a:
                        mapping["source"] = _select_column("Origen", cols, mapping.get("source", ""), f"gm_src_{idx}")
                        mapping["target"] = _select_column("Destino", cols, mapping.get("target", ""), f"gm_dst_{idx}")
                    with b:
                        mapping["type"] = _select_column("Tipo de evento", cols, mapping.get("type", ""), f"gm_type_{idx}", optional=True)
                        mapping["direction"] = _select_column("Dirección", cols, mapping.get("direction", ""), f"gm_dir_{idx}", optional=True)
                    with c:
                        mapping["datetime"] = _select_column("Fecha y hora", cols, mapping.get("datetime", ""), f"gm_dt_{idx}", optional=True)
                        mapping["time"] = _select_column("Hora (si está separada)", cols, mapping.get("time", ""), f"gm_time_{idx}", optional=True)
                    d, e, f = st.columns(3)
                    with d:
                        mapping["duration"] = _select_column("Duración", cols, mapping.get("duration", ""), f"gm_dur_{idx}", optional=True)
                        mapping["imei"] = _select_column("IMEI", cols, mapping.get("imei", ""), f"gm_imei_{idx}", optional=True)
                    with e:
                        mapping["imsi"] = _select_column("IMSI/SIM", cols, mapping.get("imsi", ""), f"gm_imsi_{idx}", optional=True)
                        mapping["antenna"] = _select_column("Antena / celda", cols, mapping.get("antenna", ""), f"gm_ant_{idx}", optional=True)
                    with f:
                        mapping["latitude"] = _select_column("Latitud", cols, mapping.get("latitude", ""), f"gm_lat_{idx}", optional=True)
                        mapping["longitude"] = _select_column("Longitud", cols, mapping.get("longitude", ""), f"gm_lon_{idx}", optional=True)
                    configs.append(mapping)
            if not profiles:
                return
            a, b, c = st.columns([1.4, 1.4, 1])
            case_name = a.text_input("Nombre del caso", value=st.session_state.get("gm_case_name", (current or {}).get("case_name", "Caso Sentinel")), key="gm_case_name")
            target_text = b.text_input("Hasta 4 líneas objetivo (separadas por coma)", value=st.session_state.get("gm_targets_text", ""), key="gm_targets_text")
            tolerance = c.number_input("Tolerancia deduplicación (s)", min_value=0, max_value=3600, value=int(st.session_state.get("gm_tolerance", 30)), step=5, key="gm_tolerance")
            manual_names = st.text_input("Personas a registrar sin atribuir automáticamente (opcional)", key="gm_manual_persons", help="Se crean como entidades PERSONA pendientes; no se conectan a teléfonos hasta una relación manual.")
            keep_manual = st.checkbox("Conservar las fichas, fotos y vínculos manuales del expediente actual", value=True, key="gm_keep_manual") if current else False
            if current:
                st.caption("Los eventos CDR se reconstruyen con los archivos seleccionados. La casilla conserva las personas, sus atributos documentados y su historial.")
            if st.button("Construir mapa investigativo", type="primary", key="gm_build_map"):
                targets = [x.strip() for x in target_text.split(",") if x.strip()][:4]
                persons = [x.strip() for x in manual_names.split(",") if x.strip()]
                state = build_state(profiles, configs, tolerance=int(tolerance), case_name=case_name or "Caso Sentinel", target_labels=targets, manual_persons=persons)
                if current and keep_manual:
                    state = preserve_manual_context(current, state)
                set_state(state)
                st.session_state["gm_graph_loaded_notice"] = f"Mapa construido: {len(state['entities'])} entidades, {len(state['events'])} eventos y {len(state['relationships'])} relaciones observadas."
                st.rerun()
        else:
            upload = st.file_uploader("Archivo de proyecto", type=["json", "xlsx", "xls"], accept_multiple_files=False, key="gm_project_upload")
            if upload and st.button("Cargar proyecto", type="primary", key="gm_project_load"):
                try:
                    state = project_from_upload(upload)
                    set_state(state)
                    st.session_state["gm_graph_loaded_notice"] = "Proyecto cargado conservando su procedencia."
                    st.rerun()
                except Exception as error:
                    st.error(f"No se pudo cargar el proyecto: {error}")


def render_identity_legend() -> None:
    pills = "".join(f'<span style="display:inline-flex;align-items:center;gap:.3rem;margin:.2rem .35rem .2rem 0;padding:.25rem .55rem;border-radius:999px;background:{ENTITY_COLORS.get(kind, "#64748b")}18;color:#334155;font-size:.8rem"><span>{ENTITY_ICONS.get(kind, "•")}</span>{escape(kind)}</span>' for kind in ENTITY_TYPES)
    st.markdown(f'<div style="padding:.5rem 0 .8rem">{pills}</div>', unsafe_allow_html=True)
    st.caption("Los iconos identifican el tipo de actor. Los colores son editables; consulta el origen y la confianza en la ficha del vínculo. Ámbar discontinuo: inferencia. Punteado: pendiente o probable. Se excluyen los vínculos descartados. Una comunicación no acredita parentesco ni titularidad.")


def render_case_exports(state: dict) -> None:
    st.download_button("Descargar expediente Excel", export_excel(state), file_name=f"{state.get('case_id','caso')}_identidad.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="gm_export_xlsx")
    st.download_button("Descargar expediente JSON", export_json(state), file_name=f"{state.get('case_id','caso')}_identidad.json", mime="application/json", key="gm_export_json")


def map_view_data(state: dict, focus: str, compare: str, depth: int, minimum: int,
                  sources: list[str], types: list[str], mode: str, limit: int) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    filtered = {**state}
    filtered["entities"] = [row for row in state.get("entities", []) if row.get("entity_type") in (["PERSONA"] if mode == "organigrama" else types)]
    allowed = {row["entity_id"] for row in filtered["entities"]}
    filtered["relationships"] = [rel for rel in state.get("relationships", [])
        if rel.get("source_id") in allowed and rel.get("target_id") in allowed
        and (mode != "organigrama" or rel.get("relation_type") in HIERARCHY_RELATIONS)]
    entities, relations = relationship_graph(filtered, focus, depth, minimum, sources)
    if compare and compare != focus:
        extra_nodes, extra_edges = relationship_graph(filtered, compare, depth, minimum, sources)
        entities = pd.concat([entities, extra_nodes]).drop_duplicates("entity_id")
        relations = pd.concat([relations, extra_edges]).drop_duplicates("relation_id")
    total = len(entities)
    if total > limit:
        degree = Counter(relations["source_id"].tolist() + relations["target_id"].tolist())
        selected = sorted(entities["entity_id"], key=lambda key: (key not in {focus, compare, state.get("canvas_selection")}, -degree[key], key))[:limit]
        entities = entities[entities["entity_id"].isin(selected)]
        relations = relations[relations["source_id"].isin(selected) & relations["target_id"].isin(selected)]
    return entities, relations, total


def render_person_editor(state: dict) -> None:
    people, labels = _options_with_label(state, types=("PERSONA",))
    with st.expander("Fichas de personas · crear, completar o actualizar", expanded=not people):
        st.caption("Registra la identidad, añade una fotografía y documenta sus atributos. Las personas con el mismo nombre permanecen separadas por su ID.")
        pending = st.session_state.pop("gm_person_pending_id", None)
        if pending in people:
            st.session_state["gm_person_select"] = pending
        if st.session_state.get("gm_person_select") not in [""] + people:
            st.session_state.pop("gm_person_select", None)
        selected = st.selectbox("Ficha a editar", [""] + people,
            format_func=lambda key: "＋ Registrar nueva persona" if not key else labels[key] + " · " + key[-6:],
            key="gm_person_select")
        current = entity_lookup(state).get(selected, {})
        metadata = entity_metadata(current)
        prefix = "gm_person_" + (selected or "new") + "_" + str(len(state.get("entity_history", [])))
        photo = portrait_uri(state, current)
        if photo:
            st.image(BytesIO(base64.b64decode(photo.split(",", 1)[1])), width=110, caption="Fotografía de la ficha actual")
        with st.form(prefix + "_form"):
            a, b = st.columns(2)
            label = a.text_input("Nombre completo", value=text_value(current.get("label")), key=prefix + "_name")
            confidence = b.selectbox("Confianza de la identidad", CONFIDENCE_LEVELS,
                index=CONFIDENCE_LEVELS.index(current.get("confidence")) if current.get("confidence") in CONFIDENCE_LEVELS else 3, key=prefix + "_confidence")
            fields = {}
            for index, (key, title) in enumerate(PROFILE_FIELDS):
                col = a if index % 2 == 0 else b
                fields[key] = col.text_input(title, value=text_value(metadata.get(key)), key=prefix + "_" + key)
            source = st.text_input("Fuente de la ficha", value=text_value(current.get("source_detail")), key=prefix + "_source",
                help="Documento, entrevista, informe u otra referencia que respalda los datos capturados.")
            notes = st.text_area("Observaciones de la persona", value=text_value(current.get("notes")), key=prefix + "_notes")
            evidence_lookup = {row["evidence_id"]: row.get("title", row["evidence_id"]) for row in state.get("evidences", [])}
            previous_ids = list(filter(None, text_value(current.get("evidence_ids")).split(",")))
            evidence_options = list(dict.fromkeys(list(evidence_lookup) + previous_ids))
            evidence_ids = st.multiselect("Evidencias de la ficha", evidence_options, default=previous_ids,
                format_func=lambda key: evidence_lookup.get(key, key) + " · " + key, key=prefix + "_evidence")
            image_file = st.file_uploader("Fotografía (JPG, PNG o WebP · hasta 5 MB)", type=["jpg", "jpeg", "png", "webp"], key=prefix + "_photo")
            photo_source = st.text_input("Fuente de la fotografía", key=prefix + "_photo_source")
            remove_photo = st.checkbox("Retirar la fotografía de esta ficha", value=False, key=prefix + "_remove_photo") if photo else False
            saved = st.form_submit_button("Guardar ficha", type="primary")
        if saved:
            try:
                portrait = prepare_portrait(image_file) if image_file is not None else None
                updated = copy.deepcopy(state)
                person_id = save_person_profile(updated, selected, label, fields, confidence=confidence, source=source,
                    notes=notes, evidence_ids=evidence_ids, portrait=portrait, photo_source=photo_source, remove_photo=remove_photo)
                set_state(updated)
                st.session_state["gm_person_pending_id"] = person_id
                st.session_state["gm_graph_loaded_notice"] = "Ficha guardada con su historial de cambios."
                st.rerun()
            except (ValueError, OSError) as error:
                st.error(str(error))
        if selected:
            st.markdown("**Vincular un teléfono, dispositivo u otro atributo**")
            st.caption("Cada atributo crea una entidad y un vínculo documentado. No se atribuye automáticamente el uso de una línea.")
            with st.form("gm_person_attribute_" + selected):
                a, b = st.columns(2)
                kind = a.selectbox("Tipo de atributo", [x for x in ENTITY_TYPES if x not in {"PERSONA", "CASO", "EVENTO"}], key="gm_attribute_type_" + selected)
                value = b.text_input("Valor / etiqueta del atributo", key="gm_attribute_value_" + selected)
                relation = a.selectbox("Vínculo con la persona", ["UTILIZA", "ASOCIADO_A", "PROPIETARIO_DE", "TIENE_PERFIL", "RESIDE_EN", "TRABAJA_EN", "RELACION_DOCUMENTAL"], key="gm_attribute_relation_" + selected)
                attribute_confidence = b.selectbox("Confianza del vínculo", CONFIDENCE_LEVELS, index=3, key="gm_attribute_confidence_" + selected)
                attribute_source = st.text_input("Fuente del atributo y vínculo", key="gm_attribute_source_" + selected)
                attribute_evidence = st.multiselect("Evidencias del atributo", list(evidence_lookup), format_func=lambda key: evidence_lookup[key] + " · " + key, key="gm_attribute_evidence_" + selected)
                if st.form_submit_button("Vincular atributo"):
                    if not value.strip() or not attribute_source.strip():
                        st.error("Escribe el valor del atributo y su fuente.")
                    else:
                        updated = copy.deepcopy(state)
                        attribute_id = add_entity(updated, kind, value, source_type="MANUAL", source_detail=attribute_source,
                            confidence=attribute_confidence, evidence_ids=attribute_evidence)
                        add_manual_relation_to_state(updated, selected, attribute_id, relation, source=attribute_source,
                            confidence=attribute_confidence, evidence_ids=attribute_evidence)
                        set_state(updated)
                        st.session_state["gm_graph_loaded_notice"] = "Atributo vinculado con fuente y confianza."
                        st.rerun()
            if metadata.get("photo_asset") in state.get("assets", {}):
                original = state["assets"][metadata["photo_asset"]]
                st.download_button("Descargar fotografía original", data=base64.b64decode(original["data"]),
                    file_name=original.get("file_name", "fotografia"), mime=original.get("mime_type", "image/jpeg"), key="gm_photo_original_" + selected)
            history = [row for row in state.get("entity_history", []) if row.get("entity_id") == selected]
            if history:
                st.caption(f"Revisiones guardadas: {len(history)}. El historial íntegro se conserva en las exportaciones de proyecto.")


def render_identity_tab(state: dict) -> None:
    render_section("Editor de diagrama", "Arrastra actores al lienzo, completa sus fichas y conecta sus vínculos aquí mismo.", "01")
    if st.session_state.pop("gm_canvas_reveal", None):
        for key in ("gm_graph_focus", "gm_graph_compare", "gm_graph_scope", "gm_graph_types", "gm_graph_sources"):
            st.session_state.pop(key, None)
    mode_label = st.radio("Distribución del diagrama", ["Red de vínculos", "Organigrama"], horizontal=True, key="gm_graph_layout")
    mode = "organigrama" if mode_label == "Organigrama" else "red"
    source_options = sorted(set(SOURCE_TYPES) | set(x.get("source_type", "") for x in state.get("relationships", [])))
    if st.button("Limpiar filtros del mapa", key="gm_clear_identity_filters"):
        for key in ("gm_graph_focus", "gm_graph_compare", "gm_graph_depth", "gm_graph_minimum", "gm_graph_sources", "gm_graph_scope", "gm_graph_types", "gm_graph_limit"):
            st.session_state.pop(key, None)
        st.rerun()
    a, b, c, d = st.columns([2, 2, 1, 1])
    ids, labels = _options_with_label(state, types=("PERSONA",) if mode == "organigrama" else None)
    for key in ("gm_graph_focus", "gm_graph_compare"):
        if st.session_state.get(key) not in [""] + ids:
            st.session_state.pop(key, None)
    focus = a.selectbox("Entidad focal", [""] + ids, format_func=lambda key: "Vista general" if not key else labels[key], key="gm_graph_focus")
    compare_ids = [key for key in ids if key != focus]
    if st.session_state.get("gm_graph_compare") not in [""] + compare_ids:
        st.session_state.pop("gm_graph_compare", None)
    compare = b.selectbox("Comparar con", [""] + compare_ids,
        format_func=lambda key: "Sin segundo centro" if not key else labels[key], disabled=mode == "organigrama", key="gm_graph_compare")
    depth = c.selectbox("Saltos", [1, 2, 3, 4], index=1, key="gm_graph_depth")
    minimum = d.number_input("Mín. eventos CDR", min_value=0, value=0, step=1, key="gm_graph_minimum")
    e, f, g = st.columns([1.6, 2.4, 1.3])
    sources = e.multiselect("Origen de vínculos", source_options,
        default=[x for x in source_options if x in {"IMPORTADO", "MANUAL"}], key="gm_graph_sources")
    if mode == "organigrama":
        f.selectbox("Mostrar", ["Personas"], disabled=True, key="gm_org_scope")
        types = ["PERSONA"]
    else:
        scope = f.selectbox("Mostrar", ["Todas las entidades", "Personas y teléfonos", "Personas", "Elegir tipos"], key="gm_graph_scope")
        types = ["PERSONA"] if scope == "Personas" else ["PERSONA", "TELEFONO"] if scope == "Personas y teléfonos" else list(ENTITY_TYPES)
        if scope == "Elegir tipos":
            types = st.multiselect("Tipos de entidad", list(ENTITY_TYPES), default=list(ENTITY_TYPES), key="gm_graph_types")
    limit = g.select_slider("Máximo de nodos", options=[20, 40, 60, 80, 120, 160, 200, 300], value=80, key="gm_graph_limit")
    if mode == "organigrama":
        compare = ""
        st.caption("Conecta dos personas con Dirige a o Supervisa a y pulsa Ordenar para disponer los niveles. Usa Red de vínculos para mezclar personas, empresas y otros actores.")
    else:
        st.caption("Elige dos centros para separar sus vecinos y colocar los contactos directos comunes entre ambos. Amplía los saltos para explorar sus atributos y comunicaciones.")
    visible_entities, visible_relations, total = map_view_data(state, focus, compare, int(depth), int(minimum), sources, types, mode, int(limit))
    if total > limit:
        st.info(f"Se muestran {len(visible_entities)} de {total} entidades que coinciden con los filtros. Se priorizan los centros seleccionados y las entidades más conectadas. El expediente conserva todos los registros.")
    html = identity_html(visible_entities, visible_relations, focus=focus, compare=compare, mode=mode, state=state)
    payload = diagram_payload(state, visible_entities, visible_relations, focus=focus, compare=compare, mode=mode)
    render_canvas_editor(state, payload)
    st.download_button("Descargar diagrama interactivo (HTML)", html.encode("utf-8"), f"sentinel_{mode}.html", "text/html", key="gm_diagram_download", disabled=visible_entities.empty)
    st.caption("Los cambios y posiciones quedan guardados en esta sesión. Descarga el expediente JSON o Excel para continuar después o en otro equipo. El HTML es una copia de consulta del diagrama.")
    render_kpi_row([
        {"label": "Entidades visibles", "value": len(visible_entities), "tone": "primary"},
        {"label": "Relaciones visibles", "value": len(visible_relations)},
        {"label": "Personas en el caso", "value": sum(row.get("entity_type") == "PERSONA" for row in state.get("entities", []))},
        {"label": "Evidencias", "value": len(state.get("evidences", []))},
    ], columns=4)
    render_person_editor(state)
    with st.expander("Leyenda de entidades y procedencia"):
        render_identity_legend()


def render_communications_tab(state: dict) -> None:
    render_section("Comunicaciones", "Eventos CDR catalogados y soporte original. Los tipos no reconocidos permanecen como NO_CLASIFICADO.", "02")
    events = frame_from_records(state.get("events", []), EVENT_COLUMNS)
    relations = frame_from_records([x for x in state.get("relationships", []) if x.get("relation_type") == "COMUNICACION"], RELATION_COLUMNS)
    if events.empty:
        st.info("Carga uno o varios CDR para ver comunicaciones.")
        return
    communication_events = events[events["event_type"].isin(VALID_EVENT_TYPES)]
    ids, labels = _options_with_label(state, types=("TELEFONO",))
    a, b, c, d = st.columns([1.4, 1.4, 1.4, 1])
    selected_line = a.selectbox("Línea objetivo", [""] + ids, format_func=lambda x: "Todas" if not x else labels.get(x, x), key="gm_comm_target")
    external = b.text_input("Número externo", key="gm_comm_external")
    selected = c.multiselect("Tipos de evento", list(VALID_EVENT_TYPES), default=list(VALID_EVENT_TYPES), key="gm_comm_types")
    minimum = d.number_input("Mín. eventos", min_value=0, value=0, step=1, key="gm_comm_minimum")
    date_filter = st.text_input("Fecha exacta (YYYY-MM-DD, opcional)", key="gm_comm_date")
    selected_label = entity_lookup(state).get(selected_line, {}).get("label", "") if selected_line else ""
    shown = communication_events[communication_events["event_type"].isin(selected)]
    if selected_label:
        shown = shown[(shown["source_id"] == selected_label) | (shown["target_id"] == selected_label)]
    if external.strip():
        shown = shown[shown["source_id"].str.contains(external.strip(), na=False) | shown["target_id"].str.contains(external.strip(), na=False)]
    if date_filter.strip():
        shown = shown[shown["datetime"].str.startswith(date_filter.strip(), na=False)]
    if not communication_events.empty and shown.empty:
        st.info("No hay eventos de comunicación con esos filtros.")
    render_kpi_row([{"label": "Filas fuente", "value": len(state.get("support", []))}, {"label": "Eventos lógicos", "value": len(events)}, {"label": "NO_CLASIFICADO", "value": int((events["event_type"] == "NO_CLASIFICADO").sum())}, {"label": "Relaciones de comunicación", "value": len(relations)}], columns=4)
    st.dataframe(shown, use_container_width=True)
    with st.expander("Registros NO_CLASIFICADO (solo soporte, sin relación)"):
        st.dataframe(events[events["event_type"] == "NO_CLASIFICADO"], use_container_width=True)
    with st.expander("Ver relaciones agregadas"):
        lookup = entity_lookup(state)
        relation_view = relations.copy()
        relation_view["origen"] = relation_view["source_id"].map(lambda x: lookup.get(x, {}).get("label", x))
        relation_view["destino"] = relation_view["target_id"].map(lambda x: lookup.get(x, {}).get("label", x))
        relation_view = relation_view[pd.to_numeric(relation_view["support_count"], errors="coerce").fillna(0) >= int(minimum)]
        st.dataframe(relation_view, use_container_width=True)
    with st.expander("Ver todas las filas de soporte original"):
        st.dataframe(frame_from_records(state.get("support", []), SUPPORT_COLUMNS), use_container_width=True)


def render_personal_tab(state: dict) -> None:
    render_section("Relaciones personales", "Solo relaciones registradas explícitamente por una persona usuaria; no se infiere parentesco.", "03")
    render_info_panel("Lenguaje de observación", "Una llamada, contacto común, domicilio, IMEI, antena, horario, red social o coincidencia nominal no prueba por sí sola parentesco, convivencia ni titularidad. Registra una relación manual y su evidencia cuando exista.", "info")
    relations = [r for r in state.get("relationships", []) if r.get("relation_type") in PERSONAL_RELATIONS]
    if relations:
        view = pd.DataFrame(relations)
        lookup = entity_lookup(state)
        view.insert(2, "origen", view["source_id"].map(lambda x: lookup.get(x, {}).get("label", x)))
        view.insert(3, "destino", view["target_id"].map(lambda x: lookup.get(x, {}).get("label", x)))
        st.dataframe(view, use_container_width=True)
    else:
        st.info("Todavía no hay relaciones personales documentadas. Añádelas desde Edición manual.")


def render_support_tab(state: dict) -> None:
    render_section("Relaciones y soporte", "Filtra por confianza, origen y estado para distinguir observado, manual, inferido y descartado.", "04")
    relations = frame_from_records(state.get("relationships", []), RELATION_COLUMNS)
    if relations.empty:
        st.info("No hay relaciones para revisar.")
        return
    a, b, c = st.columns(3)
    with a:
        confidence = st.multiselect("Confianza", list(CONFIDENCE_LEVELS), default=list(CONFIDENCE_LEVELS), key="gm_rel_confidence")
    with b:
        source_types = st.multiselect("Origen", list(SOURCE_TYPES), default=list(SOURCE_TYPES), key="gm_rel_source")
    with c:
        relation_types = st.multiselect("Tipo", sorted(relations["relation_type"].unique()), default=sorted(relations["relation_type"].unique()), key="gm_rel_type")
    shown = relations[relations["confidence"].isin(confidence) & relations["source_type"].isin(source_types) & relations["relation_type"].isin(relation_types)]
    st.dataframe(shown, use_container_width=True)
    if not shown.empty:
        relation_id = st.selectbox("Abrir ficha de relación", [""] + shown["relation_id"].tolist(), key="gm_support_relation")
        if relation_id:
            selected = next((r for r in state.get("relationships", []) if r.get("relation_id") == relation_id), {})
            st.json(selected)
            evidence_ids = set(filter(None, text_value(selected.get("evidence_ids")).split(",")))
            event_ids = {e.get("event_id") for e in state.get("events", []) if e.get("evidence_id") in evidence_ids}
            support = frame_from_records(state.get("support", []), SUPPORT_COLUMNS)
            support = support[support["event_id"].isin(event_ids)] if event_ids else support.iloc[0:0]
            st.markdown("**Registros CDR soporte**")
            st.dataframe(support, use_container_width=True)
    st.caption("La columna evidence_ids enlaza con EVIDENCIAS; source_hash, archivo, hoja y fila se conservan en SOPORTE_CDR.")


def render_timeline_tab(state: dict) -> None:
    render_section("Cronología", "Orden temporal de eventos y relaciones documentadas.", "05")
    events = frame_from_records(state.get("events", []), EVENT_COLUMNS)
    if events.empty:
        st.info("No hay eventos fechados.")
        return
    events["_dt"] = pd.to_datetime(events["datetime"], errors="coerce")
    events = events.sort_values("_dt", na_position="last").drop(columns=["_dt"])
    choices = st.multiselect("Tipos", sorted(events["event_type"].unique()), default=sorted(events["event_type"].unique()), key="gm_timeline_types")
    st.dataframe(events[events["event_type"].isin(choices)], use_container_width=True)


def render_geo_tab(state: dict) -> None:
    render_section("Mapa geográfico", "Representación local de coordenadas CDR; no se envían datos a servicios externos.", "06")
    geo_types = ("ANTENA", "DOMICILIO", "EMPRESA", "UBICACION")
    all_locations = [x for x in state.get("entities", []) if x.get("entity_type") in geo_types]
    location_types = st.multiselect("Tipo de ubicación", list(geo_types), default=list(geo_types), key="gm_geo_types")
    phone_ids, phone_labels = _options_with_label(state, types=("TELEFONO",))
    person_ids, person_labels = _options_with_label(state, types=("PERSONA",))
    a, b, c = st.columns(3)
    selected_phone = a.selectbox("Filtrar por teléfono", [""] + phone_ids, format_func=lambda x: "Todos" if not x else phone_labels.get(x, x), key="gm_geo_phone")
    selected_person = b.selectbox("Filtrar por persona", [""] + person_ids, format_func=lambda x: "Todas" if not x else person_labels.get(x, x), key="gm_geo_person")
    date_text = c.text_input("Fecha (YYYY-MM-DD, opcional)", key="gm_geo_date")
    limit = st.slider("Máximo de ubicaciones a renderizar", 25, 1000, 250, 25, key="gm_geo_limit")
    allowed_ids = {x["entity_id"] for x in all_locations if x.get("entity_type") in location_types}
    labels_by_id = entity_lookup(state)
    phone_label = labels_by_id.get(selected_phone, {}).get("label", "") if selected_phone else ""
    person_phone_labels = set()
    if selected_person:
        for rel in state.get("relationships", []):
            if rel.get("source_id") == selected_person and rel.get("relation_type") == "UTILIZA":
                person_phone_labels.add(labels_by_id.get(rel.get("target_id"), {}).get("label", ""))
    if selected_phone or selected_person or date_text.strip():
        matching_coords = set()
        for event in state.get("events", []):
            if (phone_label or person_phone_labels) and event.get("source_id") not in ({phone_label} | person_phone_labels):
                continue
            if date_text.strip() and not text_value(event.get("datetime")).startswith(date_text.strip()):
                continue
            lat, lon = text_value(event.get("latitude")), text_value(event.get("longitude"))
            if lat and lon:
                matching_coords.add(f"{lat},{lon}")
        allowed_ids = {x["entity_id"] for x in all_locations if x["entity_id"] in allowed_ids and x.get("label") in matching_coords}
        if not allowed_ids:
            allowed_ids = {"__sin_resultados__"}
    locations = [x for x in all_locations if x["entity_id"] in allowed_ids and x.get("entity_type") in location_types]
    st.caption(f"Disponibles: {len(all_locations)} · seleccionadas: {len(locations)} · mostradas como máximo: {limit}. Usa filtros o exporta para revisar el universo completo.")
    components.html(render_geo_svg(state, entity_filter=list(allowed_ids), limit=limit), height=600, scrolling=False)
    if locations:
        point_ids = [x["entity_id"] for x in locations]
        point = st.selectbox("Abrir ficha de punto", [""] + point_ids, format_func=lambda x: "Selecciona un punto" if not x else f"{labels_by_id.get(x, {}).get('entity_type', '')} · {labels_by_id.get(x, {}).get('label', x)}", key="gm_geo_point")
        if point:
            st.json(labels_by_id.get(point, {}))
        st.dataframe(frame_from_records(locations, ENTITY_COLUMNS), use_container_width=True)
    else:
        st.info("No hay ubicaciones con coordenadas en el filtro seleccionado.")


def render_evidence_tab(state: dict) -> None:
    render_section("Evidencias y procedencia", "Cada fila importada conserva archivo, hoja, fila, hash y hora de captura.", "07")
    evidences = frame_from_records(state.get("evidences", []), EVIDENCE_COLUMNS)
    if evidences.empty:
        st.info("No hay evidencias registradas.")
        return
    kind = st.multiselect("Tipo de evidencia", sorted(evidences["evidence_type"].unique()), default=sorted(evidences["evidence_type"].unique()), key="gm_evidence_types")
    st.dataframe(evidences[evidences["evidence_type"].isin(kind)], use_container_width=True)
    st.download_button("Exportar evidencias JSON", evidences.to_json(orient="records", force_ascii=False, indent=2), "evidencias.json", "application/json", key="gm_evidence_export")


def render_analysis_tab(state: dict) -> None:
    render_section("Análisis dinámico", "Las métricas se calculan con las líneas objetivo seleccionadas; no hay números de teléfono codificados.", "08")
    phone_ids = _entity_ids_by_type(state, "TELEFONO")
    labels = {x["entity_id"]: x.get("label", x["entity_id"]) for x in state.get("entities", []) if x.get("entity_type") == "TELEFONO"}
    selected = st.multiselect("Líneas objetivo (hasta 4)", phone_ids, default=[x for x in state.get("targets", []) if x in phone_ids], format_func=lambda x: labels.get(x, x), max_selections=4, key="gm_analysis_targets")
    tables = analysis_tables(state, selected)
    render_kpi_row([{"label": "Objetivos", "value": len(selected)}, {"label": "Contactos 4/4", "value": len(common_contacts(state, selected, 4)) if len(selected) >= 4 else 0}, {"label": "Contactos 3/4", "value": len(common_contacts(state, selected, 3)) if len(selected) >= 3 else 0}, {"label": "Contactos 2/4", "value": len(common_contacts(state, selected, 2)) if len(selected) >= 2 else 0}], columns=4)
    tabs = st.tabs(["Líneas", "Objetivo ↔ objetivo", "Comunes", "Individuales", "Atributos compartidos", "Coincidencias", "Pendientes"])
    with tabs[0]:
        st.dataframe(tables["lineas_objetivo"], use_container_width=True)
    with tabs[1]:
        st.dataframe(tables["objetivo_objetivo"], use_container_width=True)
    with tabs[2]:
        for minimum in (4, 3, 2):
            if len(selected) >= minimum:
                st.markdown(f"**Contactos {minimum}/{len(selected)}**")
                st.dataframe(common_contacts(state, selected, minimum), use_container_width=True)
    with tabs[3]:
        st.dataframe(tables["contactos_individuales"], use_container_width=True)
    with tabs[4]:
        st.dataframe(tables["imeis_antenas"], use_container_width=True)
    with tabs[5]:
        st.dataframe(tables["coincidencias"], use_container_width=True)
    with tabs[6]:
        st.dataframe(tables["relaciones_pendientes"], use_container_width=True)
    lookup = entity_lookup(state)
    link_counts = Counter()
    for relation in state.get("relationships", []):
        if relation.get("status") != "DESCARTADA":
            link_counts[relation.get("source_id", "")] += 1
            link_counts[relation.get("target_id", "")] += 1
    with st.expander("Entidades con más vínculos y soporte documental", expanded=False):
        link_rows = [{"entidad": lookup.get(entity_id_value, {}).get("label", entity_id_value), "tipo": lookup.get(entity_id_value, {}).get("entity_type", ""), "vinculos": count} for entity_id_value, count in link_counts.most_common(25)]
        support_rows = [{"entidad": lookup.get(entity_id_value, {}).get("label", entity_id_value), "tipo": lookup.get(entity_id_value, {}).get("entity_type", ""), "evidencias": len(list(filter(None, text_value(lookup.get(entity_id_value, {}).get("evidence_ids")).split(","))))} for entity_id_value in link_counts]
        if not link_rows:
            st.info("Aún no hay vínculos para este ranking. Las filas importadas se conservan en Evidencias y Comunicaciones.")
        st.dataframe(pd.DataFrame(link_rows, columns=["entidad", "tipo", "vinculos"]), use_container_width=True)
        st.dataframe(pd.DataFrame(support_rows, columns=["entidad", "tipo", "evidencias"]).sort_values("evidencias", ascending=False), use_container_width=True)
    if not selected:
        st.caption("Selecciona objetivos para activar comparación de contactos, objetivo↔objetivo y coberturas.")


def render_manual_tab(state: dict) -> None:
    render_section("Edición manual", "Altas append-only con usuario, fecha, confianza, fuente y notas; nunca se sobreescriben relaciones anteriores.", "09")
    left, right = st.columns(2)
    with left:
        st.markdown("#### Nueva entidad")
        with st.form("gm_manual_entity_form", clear_on_submit=True):
            entity_type_value = st.selectbox("Tipo de entidad", ENTITY_TYPES, key="gm_manual_entity_type")
            label = st.text_input("Etiqueta", key="gm_manual_entity_label")
            alias = st.text_input("Alias (opcional)", key="gm_manual_entity_alias")
            role = st.text_input("Rol / función (opcional)", key="gm_manual_entity_role")
            confidence = st.selectbox("Confianza", CONFIDENCE_LEVELS, index=3, key="gm_manual_entity_confidence")
            source_detail = st.text_input("Fuente / detalle", key="gm_manual_entity_source")
            lat_text = st.text_input("Latitud (opcional)", key="gm_manual_entity_lat")
            lon_text = st.text_input("Longitud (opcional)", key="gm_manual_entity_lon")
            notes = st.text_area("Notas", key="gm_manual_entity_notes")
            if st.form_submit_button("Agregar entidad"):
                if not label.strip():
                    st.error("Escribe una etiqueta.")
                else:
                    metadata = {}
                    if parse_coordinate(lat_text) is not None and parse_coordinate(lon_text) is not None:
                        metadata = {"latitude": parse_coordinate(lat_text), "longitude": parse_coordinate(lon_text)}
                    if alias.strip():
                        metadata["alias"] = alias.strip()
                    if role.strip():
                        metadata["role"] = role.strip()
                    add_manual_entity_to_state(state, entity_type_value, label, confidence, notes, source_detail, metadata)
                    set_state(state)
                    st.success("Entidad manual agregada y auditada.")
                    st.rerun()
        st.markdown("#### Nueva evidencia")
        with st.form("gm_manual_evidence_form", clear_on_submit=True):
            title = st.text_input("Título", key="gm_manual_evidence_title")
            source = st.text_input("Fuente", key="gm_manual_evidence_source")
            description = st.text_area("Descripción", key="gm_manual_evidence_description")
            raw = st.text_area("Referencia / contenido (opcional)", key="gm_manual_evidence_raw")
            if st.form_submit_button("Agregar evidencia"):
                if not title.strip():
                    st.error("Escribe un título.")
                else:
                    add_manual_evidence_to_state(state, title, source, description, raw)
                    set_state(state)
                    st.success("Evidencia manual agregada.")
                    st.rerun()
    with right:
        st.markdown("#### Nueva relación personal, jerárquica o documental")
        st.caption("Organigrama: DIRIGE_A / SUPERVISA_A / COORDINA_A apuntan al dependiente. REPORTA_A / SUBORDINADO_DE apuntan al superior. La fuente y la confianza quedan en cada vínculo.")
        ids, labels = _options_with_label(state)
        with st.form("gm_manual_relation_form", clear_on_submit=True):
            source_id = st.selectbox("Origen", ids, format_func=lambda x: labels.get(x, x), key="gm_manual_relation_source") if ids else ""
            target_id = st.selectbox("Destino", ids, format_func=lambda x: labels.get(x, x), key="gm_manual_relation_target") if ids else ""
            relation_type_value = st.selectbox("Tipo de relación", RELATION_TYPES, key="gm_manual_relation_type")
            relation_source = st.selectbox("Fuente", MANUAL_SOURCES, key="gm_manual_relation_source_detail")
            description = st.text_area("Descripción", key="gm_manual_relation_description")
            a, b = st.columns(2)
            start_date = a.date_input("Desde", value=None, key="gm_manual_relation_start")
            end_date = b.date_input("Hasta", value=None, key="gm_manual_relation_end")
            confidence = st.selectbox("Confianza", CONFIDENCE_LEVELS, index=3, key="gm_manual_relation_confidence")
            notes = st.text_area("Notas / reserva", key="gm_manual_relation_notes")
            evidence_ids = st.multiselect("Evidencia vinculada", [x["evidence_id"] for x in state.get("evidences", [])], key="gm_manual_relation_evidence")
            if st.form_submit_button("Agregar relación"):
                if not source_id or not target_id or source_id == target_id:
                    st.error("Elige origen y destino distintos.")
                elif relation_type_value in (*PERSONAL_RELATIONS, *HIERARCHY_RELATIONS) and (entity_lookup(state).get(source_id, {}).get("entity_type") != "PERSONA" or entity_lookup(state).get(target_id, {}).get("entity_type") != "PERSONA"):
                    st.error("Las relaciones personales y jerárquicas deben conectar dos entidades PERSONA. Registra primero ambas personas.")
                elif start_date and end_date and start_date > end_date:
                    st.error("La fecha final no puede ser anterior a la inicial.")
                else:
                    add_manual_relation_to_state(state, source_id, target_id, relation_type_value, start_date=start_date.isoformat() if isinstance(start_date, date) else "", end_date=end_date.isoformat() if isinstance(end_date, date) else "", source=relation_source, description=description, confidence=confidence, notes=notes, evidence_ids=evidence_ids)
                    set_state(state)
                    st.success("Relación manual agregada; la historia anterior permanece intacta.")
                    st.rerun()
    with st.expander("Auditoría de cambios", expanded=False):
        st.dataframe(frame_from_records(state.get("audit", []), ["audit_id", "timestamp", "user", "action", "object_id", "detail"]), use_container_width=True)


def render_exports_and_notice(state: dict) -> None:
    notice_slot = st.empty()
    if notice := st.session_state.pop("gm_graph_loaded_notice", None):
        notice_slot.success(notice)
    with st.container(border=True):
        a, b, c, d, e = st.columns([2.2, 1, 1, 1, 1])
        a.markdown(f"**Caso:** {escape(text_value(state.get('case_name'), 'Caso Sentinel'))}  ·  `{escape(text_value(state.get('case_id')))}`")
        b.metric("Entidades", len(state.get("entities", [])))
        c.metric("Evidencias", len(state.get("evidences", [])))
        d.metric("Eventos lógicos", len(state.get("events", [])))
        e.metric("Sin clasificar", sum(1 for x in state.get("events", []) if x.get("event_type") == "NO_CLASIFICADO"))
        st.caption("Estado: protegido por procedencia · datos importados, relaciones manuales e inferencias visibles por separado")
        render_case_exports(state)


def main() -> None:
    login_guard("Grafo Inteligente")
    render_suite_sidebar()
    # Hide only Streamlit's automatically generated page list on this page.
    # Keep the suite's custom sidebar, including its icons and controls.
    st.markdown('<style>[data-testid="stSidebarNav"], [data-testid="stSidebarNavSeparator"] {display:none !important;}</style>', unsafe_allow_html=True)
    render_page_header(
        "Sentinel · Mapa investigativo",
        "Red de vínculos y organigrama con fotografías, fichas de personas y relaciones documentadas.",
        status=f"Operativo · {APP_VERSION}",
        tags=["Fotografías", "Organigrama", "Fichas de identidad", "CDR múltiple"],
    )
    render_case_loader()
    state = get_state()
    if state is None:
        render_info_panel("Comienza con un expediente", "Carga Excel/CSV CDR o elige Expediente manual para empezar con personas y fotografías. Después completa las fichas y registra los vínculos que forman la red o el organigrama.", "info")
        if st.button("Crear diagrama vacío", type="primary", key="gm_start_canvas"):
            set_state(new_state("Diagrama de investigación"))
            st.rerun()
        return
    render_exports_and_notice(state)
    tabs = st.tabs(["Mapa de identidad", "Comunicaciones", "Relaciones personales", "Relaciones y soporte", "Cronología", "Mapa geográfico", "Evidencias", "Análisis", "Edición manual"])
    renderers = (render_identity_tab, render_communications_tab, render_personal_tab, render_support_tab, render_timeline_tab, render_geo_tab, render_evidence_tab, render_analysis_tab, render_manual_tab)
    for tab, renderer in zip(tabs, renderers):
        with tab:
            renderer(state)


if __name__ == "__main__":
    main()
