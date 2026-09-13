"""Sentinel Mapa Investigativo: identidad, comunicaciones y evidencia.

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
import hashlib
import json
import math
import re
import unicodedata
import uuid
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Go Mapper · Mapa investigativo", page_icon="🧭", layout="wide")

from guardian import login_guard
from suite_nav import render_suite_sidebar
from ui.components import render_info_panel, render_kpi_row, render_page_header, render_section


APP_VERSION = "5.0.0-identidades"
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
RELATION_TYPES = (
    "UTILIZA", "ASOCIADO_A", "TIENE_PERFIL", "PROPIETARIO_DE", "RESIDE_EN",
    "TRABAJA_EN", "UBICADO_EN", "UTILIZA_ANTENA", "COMUNICACION",
    *PERSONAL_RELATIONS, "RELACION_DOCUMENTAL",
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
    "created_at", "notes", "evidence_ids", "status", "support_count",
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
    existing = next((x for x in state["entities"] if x["entity_type"] == entity_type and x["normalized"] == normalized), None)
    if existing:
        if evidence_ids:
            prior = [text_value(existing.get("evidence_ids"))]
            existing["evidence_ids"] = ",".join(sorted(set(filter(None, prior + evidence_ids))))
        return existing["entity_id"]
    record = {
        "entity_id": entity_id(entity_type, display), "entity_type": entity_type, "label": display,
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
    frames = {sheet.upper(): pd.read_excel(book, sheet_name=sheet, dtype=str, keep_default_na=False).fillna("") for sheet in book.sheet_names}
    if "ENTIDADES" not in frames and "NODOS" in frames:
        return state_from_legacy_graph((frames["NODOS"].rename(columns={"label": "label"}), frames.get("ARISTAS", pd.DataFrame()), frames.get("EVIDENCIA_ORIGINAL", pd.DataFrame())))
    state = new_state(name.rsplit(".", 1)[0] or "Proyecto importado")
    mapping = {"ENTIDADES": "entities", "RELACIONES": "relationships", "EVENTOS": "events", "SOPORTE_CDR": "support", "EVIDENCIAS": "evidences", "AUDITORIA": "audit"}
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
    st.session_state["gm_identity_state"] = state
    for key in ("gm_graph_focus", "gm_graph_depth", "gm_graph_minimum", "gm_graph_sources"):
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
    if relations.empty:
        return entities, relations
    if source_filter:
        relations = relations[relations["source_type"].isin(source_filter)]
    relations = relations[pd.to_numeric(relations["support_count"], errors="coerce").fillna(0) >= minimum]
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


def identity_html(entities: pd.DataFrame, relations: pd.DataFrame, *, focus: str = "", height: int = 680) -> str:
    """Render a dependency-free SVG; PyVis remains an optional enhancement."""
    if entities.empty:
        return '<div style="padding:3rem;text-align:center;color:#64748b;background:#f8fafc;border-radius:18px">Sin entidades para visualizar.</div>'
    rows = entities.to_dict("records")
    count = len(rows)
    width = 1120
    center_x, center_y = width / 2, height / 2
    radius = min(300, max(120, 28 * count))
    pos = {}
    for i, row in enumerate(rows):
        angle = (2 * math.pi * i / max(count, 1)) - math.pi / 2
        pos[row["entity_id"]] = (center_x + radius * math.cos(angle), center_y + radius * math.sin(angle))
    lines = []
    for rel in relations.to_dict("records"):
        if rel.get("source_id") not in pos or rel.get("target_id") not in pos:
            continue
        x1, y1, x2, y2 = (*pos[rel["source_id"]], *pos[rel["target_id"]])
        dash = ' stroke-dasharray="7 5"' if rel.get("source_type") in {"MANUAL", "INFERIDO", "DESCARTADO"} else ""
        color = {"MANUAL": "#e879f9", "INFERIDO": "#f59e0b", "DESCARTADO": "#94a3b8"}.get(rel.get("source_type"), "#a7b8cc")
        lines.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{1.2 + min(4, float(rel.get("support_count") or 0) / 4):.1f}"{dash} marker-end="url(#arrow)"/><text x="{(x1+x2)/2:.1f}" y="{(y1+y2)/2:.1f}" font-size="10" fill="#64748b">{escape(text_value(rel.get('relation_type')))}</text>')
    circles = []
    for row in rows:
        x, y = pos[row["entity_id"]]
        et = row.get("entity_type", "")
        selected = row["entity_id"] == focus
        color = ENTITY_COLORS.get(et, "#64748b")
        label = text_value(row.get("label"), row["entity_id"])
        short = label if len(label) < 18 else label[:15] + "…"
        circles.append(f'<g><title>{escape(et)} · {escape(label)}</title><circle cx="{x:.1f}" cy="{y:.1f}" r="{26 if selected else 20}" fill="{color}" stroke="{"#fbbf24" if selected else "#ffffff"}" stroke-width="{4 if selected else 2}"/><text x="{x:.1f}" y="{y+4:.1f}" text-anchor="middle" font-size="18">{escape(ENTITY_ICONS.get(et,"•"))}</text><text x="{x:.1f}" y="{y+38:.1f}" text-anchor="middle" font-size="11" fill="#1e293b">{escape(short)}</text></g>')
    return f'''<div style="height:{height}px;overflow:hidden;border:1px solid #d8e3ef;border-radius:18px;background:linear-gradient(135deg,#fbfdff,#f1f6fb)"><svg viewBox="0 0 {width} {height}" width="100%" height="100%" role="img" aria-label="Mapa investigativo"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#94a3b8"/></marker></defs>{''.join(lines)}{''.join(circles)}</svg></div>'''


def export_excel(state: dict) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet, frame in state_frames(state).items():
            frame.to_excel(writer, index=False, sheet_name=sheet[:31])
        pd.DataFrame(state.get("imports", [])).to_excel(writer, index=False, sheet_name="IMPORTACIONES")
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
    return ids, {x["entity_id"]: f"{ENTITY_ICONS.get(x.get('entity_type'), '•')} {x.get('label', x['entity_id'])}" for x in items}


def _select_column(label: str, columns: list[str], preferred: str, key: str, optional: bool = False) -> str:
    options = (["(ninguna)"] if optional else []) + columns
    selected = preferred if preferred in options else ("(ninguna)" if optional else (columns[0] if columns else ""))
    choice = st.selectbox(label, options, index=options.index(selected) if selected in options else 0, key=key)
    return "" if choice == "(ninguna)" else choice


def render_case_loader() -> None:
    current = get_state()
    with st.expander("Cargar expediente o sustituir el mapa", expanded=current is None):
        mode = st.radio("Fuente de datos", ["CDR / Excel múltiple", "Proyecto de identidad", "Grafo legado"], horizontal=True, key="gm_load_mode")
        if mode == "CDR / Excel múltiple":
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
                with st.expander(f"{idx + 1}. {name} · {len(frame):,} filas · hoja {sheet}", expanded=len(uploads) == 1):
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
            case_name = a.text_input("Nombre del caso", value=st.session_state.get("gm_case_name", "Caso Sentinel"), key="gm_case_name")
            target_text = b.text_input("Hasta 4 líneas objetivo (separadas por coma)", value=st.session_state.get("gm_targets_text", ""), key="gm_targets_text")
            tolerance = c.number_input("Tolerancia deduplicación (s)", min_value=0, max_value=3600, value=int(st.session_state.get("gm_tolerance", 30)), step=5, key="gm_tolerance")
            manual_names = st.text_input("Personas a registrar sin atribuir automáticamente (opcional)", key="gm_manual_persons", help="Se crean como entidades PERSONA pendientes; no se conectan a teléfonos hasta una relación manual.")
            if st.button("Construir mapa investigativo", type="primary", key="gm_build_map"):
                targets = [x.strip() for x in target_text.split(",") if x.strip()][:4]
                persons = [x.strip() for x in manual_names.split(",") if x.strip()]
                state = build_state(profiles, configs, tolerance=int(tolerance), case_name=case_name or "Caso Sentinel", target_labels=targets, manual_persons=persons)
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
    st.caption("Línea sólida = dato importado/observado · línea discontinua = relación manual, inferida o descartada. La comunicación no equivale a parentesco ni titularidad.")


def render_case_exports(state: dict) -> None:
    st.download_button("Descargar expediente Excel", export_excel(state), file_name=f"{state.get('case_id','caso')}_identidad.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="gm_export_xlsx")
    st.download_button("Descargar expediente JSON", export_json(state), file_name=f"{state.get('case_id','caso')}_identidad.json", mime="application/json", key="gm_export_json")


def render_identity_tab(state: dict) -> None:
    render_section("Mapa de identidad", "Explora entidades, relaciones y la trazabilidad que sostiene cada conexión.", "01")
    source_options = sorted(set(SOURCE_TYPES) | set(x.get("source_type", "") for x in state.get("relationships", [])))
    if st.button("Limpiar filtros del mapa", key="gm_clear_identity_filters"):
        for key in ("gm_graph_focus", "gm_graph_depth", "gm_graph_minimum", "gm_graph_sources"):
            st.session_state.pop(key, None)
        st.rerun()
    a, b, c, d = st.columns([2.5, 1, 1, 1.6])
    ids, labels = _options_with_label(state)
    with a:
        focus = st.selectbox("Entidad focal", [""] + ids, format_func=lambda x: "Todas las entidades" if not x else labels.get(x, x), key="gm_graph_focus")
    depth = b.selectbox("Saltos", [1, 2, 3, 4], index=0, key="gm_graph_depth")
    minimum = c.number_input("Mín. soporte", min_value=0, value=0, step=1, key="gm_graph_minimum")
    source_filter = d.multiselect("Origen", source_options, default=[x for x in source_options if x in {"IMPORTADO", "MANUAL"}], key="gm_graph_sources")
    visible_entities, visible_relations = relationship_graph(state, focus, int(depth), int(minimum), source_filter or None)
    if len(visible_entities) > 500:
        st.warning("El mapa visual está limitado a 500 entidades para conservar legibilidad y rendimiento. El expediente completo permanece disponible en las exportaciones.")
        keep_ids = set(visible_entities.head(500)["entity_id"])
        visible_entities = visible_entities[visible_entities["entity_id"].isin(keep_ids)]
        visible_relations = visible_relations[visible_relations["source_id"].isin(keep_ids) & visible_relations["target_id"].isin(keep_ids)]
    components.html(identity_html(visible_entities, visible_relations, focus=focus), height=700, scrolling=False)
    render_kpi_row([
        {"label": "Entidades visibles", "value": len(visible_entities), "tone": "primary"},
        {"label": "Relaciones visibles", "value": len(visible_relations)},
        {"label": "Eventos deduplicados", "value": len(state.get("events", []))},
        {"label": "Ubicaciones", "value": sum(1 for x in state.get("entities", []) if x.get("entity_type") in {"UBICACION", "ANTENA", "DOMICILIO", "EMPRESA"})},
        {"label": "NO_CLASIFICADO", "value": sum(1 for x in state.get("events", []) if x.get("event_type") == "NO_CLASIFICADO")},
        {"label": "Evidencias", "value": len(state.get("evidences", []))},
    ], columns=6)
    render_identity_legend()
    if focus:
        detail = entity_lookup(state).get(focus, {})
        st.markdown(f"#### {ENTITY_ICONS.get(detail.get('entity_type'), '•')} {detail.get('label', focus)}")
        st.caption(f"Tipo: {detail.get('entity_type', '')} · Origen: {detail.get('source_type', '')} · Confianza: {detail.get('confidence', '')}")
        try:
            metadata = json.loads(detail.get("metadata", "{}"))
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        if metadata:
            st.caption(" · ".join(f"{key}: {value}" for key, value in metadata.items()))
        if detail.get("notes"):
            st.info(f"Observaciones: {detail['notes']}")
        related = [r for r in state.get("relationships", []) if r.get("source_id") == focus or r.get("target_id") == focus]
        st.dataframe(pd.DataFrame([{**r, "origen": entity_label(state, r.get("source_id", "")), "destino": entity_label(state, r.get("target_id", ""))} for r in related]), use_container_width=True)


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
        st.dataframe(pd.DataFrame(link_rows), use_container_width=True)
        st.dataframe(pd.DataFrame(support_rows).sort_values("evidencias", ascending=False), use_container_width=True)
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
        st.markdown("#### Nueva relación personal / documental")
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
                elif relation_type_value in PERSONAL_RELATIONS and (entity_lookup(state).get(source_id, {}).get("entity_type") != "PERSONA" or entity_lookup(state).get(target_id, {}).get("entity_type") != "PERSONA"):
                    st.error("Las relaciones familiares/personales deben conectar dos entidades PERSONA. Registra primero ambas personas.")
                else:
                    add_manual_relation_to_state(state, source_id, target_id, relation_type_value, start_date=start_date.isoformat() if isinstance(start_date, date) else "", end_date=end_date.isoformat() if isinstance(end_date, date) else "", source=relation_source, description=description, confidence=confidence, notes=notes, evidence_ids=evidence_ids)
                    set_state(state)
                    st.success("Relación manual agregada; la historia anterior permanece intacta.")
                    st.rerun()
    with st.expander("Auditoría de cambios", expanded=False):
        st.dataframe(frame_from_records(state.get("audit", []), ["audit_id", "timestamp", "user", "action", "object_id", "detail"]), use_container_width=True)


def render_exports_and_notice(state: dict) -> None:
    if notice := st.session_state.pop("gm_graph_loaded_notice", None):
        st.success(notice)
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
    render_page_header(
        "Sentinel · Mapa investigativo",
        "Mapa de identidad para analizar comunicaciones, relaciones personales y evidencia sin atribuir parentesco automáticamente.",
        status=f"Operativo · {APP_VERSION}",
        tags=["Identidad", "Proveniencia", "CDR múltiple", "Sin servicios externos"],
    )
    render_case_loader()
    state = get_state()
    if state is None:
        render_info_panel("Comienza con un expediente", "Carga uno o varios Excel/CSV CDR. Se usará Datos_Limpios, se excluirán Duplicados y cada fila quedará vinculada a archivo, hoja, fila, hash y hora de captura.", "info")
        return
    render_exports_and_notice(state)
    tabs = st.tabs(["Mapa de identidad", "Comunicaciones", "Relaciones personales", "Relaciones y soporte", "Cronología", "Mapa geográfico", "Evidencias", "Análisis", "Edición manual"])
    renderers = (render_identity_tab, render_communications_tab, render_personal_tab, render_support_tab, render_timeline_tab, render_geo_tab, render_evidence_tab, render_analysis_tab, render_manual_tab)
    for tab, renderer in zip(tabs, renderers):
        with tab:
            renderer(state)


if __name__ == "__main__":
    main()
