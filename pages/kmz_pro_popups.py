# -*- coding: utf-8 -*-
"""
Popups HTML para Sentinel Mapper KMZ Pro.
"""

from __future__ import annotations

import html

from .kmz_pro_utils import safe_text


def esc(value) -> str:
    return html.escape(safe_text(value))


def _row(label: str, value) -> str:
    return f"""
    <tr>
      <td style="padding:5px 8px;border-bottom:1px solid #e5e7eb;color:#475569;width:34%;"><b>{html.escape(label)}</b></td>
      <td style="padding:5px 8px;border-bottom:1px solid #e5e7eb;color:#111827;">{esc(value)}</td>
    </tr>
    """


def _notice_pericial() -> str:
    return """
    <div style="margin-top:10px;padding:8px;border-left:4px solid #64748b;background:#f8fafc;color:#334155;font-size:12px;">
      <b>Nota técnica:</b> La ubicación representada corresponde a la antena/celda servidora reportada en el CDR.
      No debe interpretarse como posición exacta del equipo terminal. El radio y el azimuth son referencias visuales configurables.
    </div>
    """


def event_popup(row: dict, mapping: dict, modo: str = "operativo", detail: str = "completo") -> str:
    tipo = row.get("__tipo", row.get(mapping.get("tipo", ""), "S/D"))
    fecha = row.get("__date", "S/D")
    hora = row.get("__time", "S/D")

    telefono = row.get(mapping.get("telefono", ""), "S/D")
    numero_a = row.get(mapping.get("numero_a", ""), "S/D")
    numero_b = row.get(mapping.get("numero_b", ""), "S/D")
    duracion = row.get(mapping.get("duracion", ""), "S/D")
    imei = row.get(mapping.get("imei", ""), "S/D")
    lat = row.get(mapping.get("latitud", ""), "S/D")
    lon = row.get(mapping.get("longitud", ""), "S/D")
    az = row.get(mapping.get("azimuth", ""), "S/D")
    direccion = row.get(mapping.get("direccion", ""), "S/D")
    plus = row.get(mapping.get("plus_code", ""), "S/D")

    rows = ""
    rows += _row("Fecha", fecha)
    rows += _row("Hora", hora)
    rows += _row("Tipo", tipo)

    if detail in {"medio", "completo"}:
        rows += _row("Teléfono investigado", telefono)
        rows += _row("Número A", numero_a)
        rows += _row("Número B / contacto", numero_b)
        rows += _row("Duración", duracion)
        rows += _row("IMEI", imei)

    if detail == "completo":
        rows += _row("Latitud", lat)
        rows += _row("Longitud", lon)
        rows += _row("Azimuth", az)
        rows += _row("Plus Code", plus)
        rows += _row("Dirección aproximada", direccion)

    nota = _notice_pericial() if str(modo).lower() == "pericial" else ""

    return f"""
    <div style="font-family:Arial, Helvetica, sans-serif;min-width:340px;max-width:520px;">
      <div style="background:#0f172a;color:white;padding:10px 12px;border-radius:8px 8px 0 0;">
        <div style="font-size:16px;font-weight:700;">Sentinel Mapper KMZ Pro</div>
        <div style="font-size:12px;opacity:.85;">Evento de comunicación</div>
      </div>
      <table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e5e7eb;">
        {rows}
      </table>
      {nota}
    </div>
    """


def antenna_popup(group_info: dict, modo: str = "operativo") -> str:
    rows = ""
    rows += _row("Antena / punto", group_info.get("name", "Antena"))
    rows += _row("Latitud", group_info.get("lat", "S/D"))
    rows += _row("Longitud", group_info.get("lon", "S/D"))
    rows += _row("Azimuth", group_info.get("azimuth", "S/D"))
    rows += _row("Total eventos", group_info.get("total", 0))
    rows += _row("Primer evento", group_info.get("first", "S/D"))
    rows += _row("Último evento", group_info.get("last", "S/D"))
    rows += _row("Tipo dominante", group_info.get("dominant_type", "S/D"))

    nota = _notice_pericial() if str(modo).lower() == "pericial" else ""

    return f"""
    <div style="font-family:Arial, Helvetica, sans-serif;min-width:340px;max-width:520px;">
      <div style="background:#1e293b;color:white;padding:10px 12px;border-radius:8px 8px 0 0;">
        <div style="font-size:16px;font-weight:700;">Antena / celda servidora</div>
        <div style="font-size:12px;opacity:.85;">Resumen de actividad asociada</div>
      </div>
      <table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e5e7eb;">
        {rows}
      </table>
      {nota}
    </div>
    """


def summary_popup(summary: dict, modo: str = "operativo") -> str:
    rows = ""
    for k, v in summary.items():
        rows += _row(str(k), v)

    nota = _notice_pericial() if str(modo).lower() == "pericial" else ""

    return f"""
    <div style="font-family:Arial, Helvetica, sans-serif;min-width:360px;max-width:560px;">
      <div style="background:#020617;color:white;padding:10px 12px;border-radius:8px 8px 0 0;">
        <div style="font-size:16px;font-weight:700;">Resumen del caso</div>
        <div style="font-size:12px;opacity:.85;">Sentinel Mapper KMZ Pro</div>
      </div>
      <table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e5e7eb;">
        {rows}
      </table>
      {nota}
    </div>
    """


def relevant_popup(title: str, row: dict, mapping: dict, motivo: str, modo: str = "operativo") -> str:
    base = event_popup(row, mapping, modo=modo, detail="medio")
    return base.replace(
        "Evento de comunicación",
        f"Evento relevante: {html.escape(motivo)}"
    ).replace(
        "Sentinel Mapper KMZ Pro",
        html.escape(title)
    )
