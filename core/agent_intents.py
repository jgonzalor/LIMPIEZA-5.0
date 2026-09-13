# core/agent_intents.py
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _norm(s: str) -> str:
    return (
        (s or "")
        .strip()
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )


def _pick_col(cols: List[str], options: List[str]) -> Optional[str]:
    low = {_norm(c): c for c in cols}
    for op in options:
        k = _norm(op)
        if k in low:
            return low[k]
    return None


def _qident(name: str) -> str:
    """Quote seguro para identificadores SQL (columnas con espacios/acentos)."""
    return '"' + str(name).replace('"', '""') + '"'


def _qlit(val: Any) -> str:
    """Quote seguro para literales SQL."""
    s = str(val) if val is not None else ""
    return "'" + s.replace("'", "''") + "'"


def _where_from_filters(filters: Dict[str, Any], df_cols: List[str]) -> str:
    if not filters:
        return ""

    parts: List[str] = []

    if filters.get("date_from"):
        parts.append(f'{_qident("Datetime")} >= TIMESTAMP {_qlit(filters["date_from"])}')
    if filters.get("date_to"):
        parts.append(f'{_qident("Datetime")} <= TIMESTAMP {_qlit(filters["date_to"])}')

    tel_col = _pick_col(df_cols, ["Teléfono", "Telefono", "TELEFONO"])
    if filters.get("telefono") and tel_col:
        parts.append(f"{_qident(tel_col)} = {_qlit(filters['telefono'])}")

    return (" AND " + " AND ".join(parts)) if parts else ""


def _select_useful_cols(df_cols: List[str]) -> List[str]:
    """
    Selecciona columnas útiles si existen, manteniendo Datetime primero.
    """
    wanted = [
        "Datetime",
        "Teléfono", "Telefono", "TELEFONO",
        "Numero A", "Número A", "NUMERO A", "MSISDN_A",
        "Numero B", "Número B", "NUMERO B", "MSISDN_B",
        "TIPO", "Tipo", "Tipo de tráfico", "SERVICIO", "SERV", "T_REG", "EVENTO",
        "DURACION", "Duracion", "Duración", "Duration",
        "LAT", "Lat", "Latitud",
        "LON", "Lon", "Longitud",
        "PLUS_CODE_NOMBRE", "PLUS_CODE",
        "IMEI", "IMSI"
    ]
    out: List[str] = []
    if "Datetime" in df_cols:
        out.append("Datetime")
    for w in wanted:
        c = _pick_col(df_cols, [w])
        if c and c not in out:
            out.append(c)
    return out


# =========================================================
# Intent: Top contactos por eventos
# =========================================================
def intent_top_contactos_por_eventos(con, df_cols: List[str], filters: Optional[Dict[str, Any]] = None, top_n: int = 10):
    num_a = _pick_col(df_cols, ["Numero A", "Número A", "NUMERO A", "A", "MSISDN_A"])
    num_b = _pick_col(df_cols, ["Numero B", "Número B", "NUMERO B", "B", "MSISDN_B"])
    tel = _pick_col(df_cols, ["Teléfono", "Telefono", "TELEFONO"])

    if not num_a or not num_b:
        return {"answer": "Este dataset no trae Numero A / Numero B.", "evidence": None, "applied_filters": filters or {}}

    na = _qident(num_a)
    nb = _qident(num_b)
    dt = _qident("Datetime")
    where_extra = _where_from_filters(filters or {}, df_cols)

    if tel:
        t = _qident(tel)
        contraparte_expr = f"""
        CASE
          WHEN CAST({na} AS VARCHAR) = CAST({t} AS VARCHAR) THEN CAST({nb} AS VARCHAR)
          WHEN CAST({nb} AS VARCHAR) = CAST({t} AS VARCHAR) THEN CAST({na} AS VARCHAR)
          ELSE CAST({nb} AS VARCHAR)
        END
        """
    else:
        contraparte_expr = f"CAST({nb} AS VARCHAR)"

    sql = f"""
    WITH base AS (
      SELECT {dt} AS Datetime, {contraparte_expr} AS contraparte
      FROM cdr
      WHERE {dt} IS NOT NULL
      {where_extra}
    ),
    grp AS (
      SELECT contraparte, COUNT(*) AS eventos, MIN(Datetime) AS desde, MAX(Datetime) AS hasta
      FROM base
      WHERE contraparte IS NOT NULL AND TRIM(contraparte) <> ''
      GROUP BY contraparte
    )
    SELECT * FROM grp
    ORDER BY eventos DESC
    LIMIT {int(top_n)};
    """
    ev = con.execute(sql).fetchdf()
    if ev is None or ev.empty:
        return {"answer": "No encontré contactos (o quedaron fuera por filtros).", "evidence": ev, "applied_filters": filters or {}}

    top1 = ev.iloc[0]
    answer = f"Contacto más frecuente: **{top1['contraparte']}** con **{int(top1['eventos'])} eventos** (rango {top1['desde']} → {top1['hasta']})."
    return {"answer": answer, "evidence": ev, "applied_filters": filters or {}}


# =========================================================
# Intent: Top ubicaciones (LAT/LON)
# =========================================================
def intent_top_ubicaciones_por_eventos(con, df_cols: List[str], filters: Optional[Dict[str, Any]] = None, top_n: int = 10, coord_precision: int = 5):
    lat = _pick_col(df_cols, ["LAT", "Lat", "Latitud", "LATITUD", "Latitude"])
    lon = _pick_col(df_cols, ["LON", "Lon", "Longitud", "LONGITUD", "Longitude"])
    pcn = _pick_col(df_cols, ["PLUS_CODE_NOMBRE", "Plus_Code_Nombre", "DIRECCION", "Direccion"])
    pc = _pick_col(df_cols, ["PLUS_CODE", "Plus_Code"])
    dur = _pick_col(df_cols, ["DURACION", "Duracion", "Duración", "Duration"])

    if not lat or not lon:
        return {"answer": "Este dataset no trae LAT/LON.", "evidence": None, "applied_filters": filters or {}}

    dt = _qident("Datetime")
    latq = _qident(lat)
    lonq = _qident(lon)
    where_extra = _where_from_filters(filters or {}, df_cols)

    dur_sel = f", CAST({_qident(dur)} AS DOUBLE) AS dur0" if dur else ", NULL::DOUBLE AS dur0"
    pcn_sel = f", CAST({_qident(pcn)} AS VARCHAR) AS pcn0" if pcn else ", NULL::VARCHAR AS pcn0"
    pc_sel = f", CAST({_qident(pc)} AS VARCHAR) AS pc0" if pc else ", NULL::VARCHAR AS pc0"

    lugar_expr = "COALESCE(NULLIF(TRIM(pcn0), ''), NULLIF(TRIM(pc0), ''), CONCAT(lat_r, ',', lon_r))"
    dur_expr = "SUM(COALESCE(dur0,0)) AS dur_total" if dur else "NULL::DOUBLE AS dur_total"

    sql = f"""
    WITH base AS (
      SELECT {dt} AS Datetime,
             CAST({latq} AS DOUBLE) AS lat0,
             CAST({lonq} AS DOUBLE) AS lon0
             {dur_sel}{pcn_sel}{pc_sel}
      FROM cdr
      WHERE {dt} IS NOT NULL AND {latq} IS NOT NULL AND {lonq} IS NOT NULL
      {where_extra}
    ),
    norm AS (
      SELECT Datetime,
             ROUND(lat0, {int(coord_precision)}) AS lat_r,
             ROUND(lon0, {int(coord_precision)}) AS lon_r,
             dur0, pcn0, pc0
      FROM base
    ),
    grp AS (
      SELECT {lugar_expr} AS lugar,
             lat_r, lon_r,
             COUNT(*) AS eventos,
             {dur_expr},
             MIN(Datetime) AS desde,
             MAX(Datetime) AS hasta
      FROM norm
      GROUP BY lugar, lat_r, lon_r
    )
    SELECT * FROM grp
    ORDER BY eventos DESC, dur_total DESC NULLS LAST
    LIMIT {int(top_n)};
    """
    ev = con.execute(sql).fetchdf()
    if ev is None or ev.empty:
        return {"answer": "No encontré ubicaciones (o quedaron fuera por filtros).", "evidence": ev, "applied_filters": filters or {}}

    top1 = ev.iloc[0]
    answer = f"Ubicación más frecuente: **{top1['lugar']}** (lat={top1['lat_r']}, lon={top1['lon_r']}) con **{int(top1['eventos'])} eventos**."
    return {"answer": answer, "evidence": ev, "applied_filters": filters or {}}


# =========================================================
# Intent: Últimos eventos / últimas llamadas
# =========================================================
def intent_ultimos_eventos(con, df_cols: List[str], filters: Optional[Dict[str, Any]] = None, top_n: int = 10, question: str = ""):
    q = _norm(question)
    dt = _qident("Datetime")
    where_extra = _where_from_filters(filters or {}, df_cols)

    # si hay columna tipo, y el usuario habla de llamadas/voz, intentamos filtrar voz
    tipo_col = _pick_col(df_cols, ["TIPO", "Tipo", "Tipo de tráfico", "SERVICIO", "SERV", "EVENTO", "T_REG"])
    tipo_filter = ""
    if tipo_col and ("llamad" in q or "voz" in q or "call" in q):
        tc = _qident(tipo_col)
        tipo_filter = f" AND (UPPER(CAST({tc} AS VARCHAR)) LIKE '%VOZ%' OR UPPER(CAST({tc} AS VARCHAR)) LIKE '%LLAM%' OR UPPER(CAST({tc} AS VARCHAR)) LIKE '%CALL%')"

    cols_out = _select_useful_cols(df_cols)
    select_list = ", ".join([_qident("Datetime") + " AS Datetime"] + [_qident(c) for c in cols_out if c != "Datetime"])

    sql = f"""
    SELECT {select_list}
    FROM cdr
    WHERE {dt} IS NOT NULL
    {where_extra}
    {tipo_filter}
    ORDER BY {dt} DESC
    LIMIT {int(top_n)};
    """
    ev = con.execute(sql).fetchdf()
    if ev is None or ev.empty:
        return {"answer": "No encontré registros recientes (o quedaron fuera por filtros).", "evidence": ev, "applied_filters": filters or {}}

    return {"answer": f"Te muestro los **últimos {min(int(top_n), len(ev))} registros** por Datetime (desc).", "evidence": ev, "applied_filters": filters or {}}


# =========================================================
# Helpers: predicados VOZ / Entrante / Saliente
# =========================================================
def _voice_pred(df_cols: List[str]) -> str:
    tipo_col = _pick_col(df_cols, ["TIPO", "Tipo", "Tipo de tráfico", "SERVICIO", "SERV", "EVENTO", "T_REG"])
    if not tipo_col:
        return ""  # sin tipo, no filtramos
    tc = _qident(tipo_col)
    return f"(UPPER(CAST({tc} AS VARCHAR)) LIKE '%VOZ%' OR UPPER(CAST({tc} AS VARCHAR)) LIKE '%LLAM%' OR UPPER(CAST({tc} AS VARCHAR)) LIKE '%CALL%')"


def _incoming_pred(df_cols: List[str]) -> str:
    preds = []

    tipo_col = _pick_col(df_cols, ["TIPO", "Tipo", "Tipo de tráfico", "SERVICIO", "SERV", "EVENTO", "T_REG"])
    if tipo_col:
        tc = _qident(tipo_col)
        preds.append(f"(UPPER(CAST({tc} AS VARCHAR)) LIKE '%ENTR%' OR UPPER(CAST({tc} AS VARCHAR)) LIKE '%IN%')")

    dir_col = _pick_col(df_cols, ["DIRECCION", "Dirección", "SENTIDO", "Sentido", "ENT_SAL", "ENT/SAL"])
    if dir_col:
        dc = _qident(dir_col)
        preds.append(f"(UPPER(CAST({dc} AS VARCHAR)) LIKE '%ENT%' OR UPPER(CAST({dc} AS VARCHAR)) LIKE '%IN%')")

    tel = _pick_col(df_cols, ["Teléfono", "Telefono", "TELEFONO"])
    num_b = _pick_col(df_cols, ["Numero B", "Número B", "NUMERO B", "MSISDN_B"])
    if tel and num_b:
        preds.append(f"CAST({_qident(num_b)} AS VARCHAR) = CAST({_qident(tel)} AS VARCHAR)")

    return "(" + " OR ".join(preds) + ")" if preds else ""


def _outgoing_pred(df_cols: List[str]) -> str:
    preds = []

    tipo_col = _pick_col(df_cols, ["TIPO", "Tipo", "Tipo de tráfico", "SERVICIO", "SERV", "EVENTO", "T_REG"])
    if tipo_col:
        tc = _qident(tipo_col)
        preds.append(f"(UPPER(CAST({tc} AS VARCHAR)) LIKE '%SAL%' OR UPPER(CAST({tc} AS VARCHAR)) LIKE '%OUT%')")

    dir_col = _pick_col(df_cols, ["DIRECCION", "Dirección", "SENTIDO", "Sentido", "ENT_SAL", "ENT/SAL"])
    if dir_col:
        dc = _qident(dir_col)
        preds.append(f"(UPPER(CAST({dc} AS VARCHAR)) LIKE '%SAL%' OR UPPER(CAST({dc} AS VARCHAR)) LIKE '%OUT%')")

    tel = _pick_col(df_cols, ["Teléfono", "Telefono", "TELEFONO"])
    num_a = _pick_col(df_cols, ["Numero A", "Número A", "NUMERO A", "MSISDN_A"])
    if tel and num_a:
        preds.append(f"CAST({_qident(num_a)} AS VARCHAR) = CAST({_qident(tel)} AS VARCHAR)")

    return "(" + " OR ".join(preds) + ")" if preds else ""


def _is_first_request(question: str) -> bool:
    qn = _norm(question)
    return any(k in qn for k in ["primer", "primera", "primero", "primeras", "primeros", "inicial", "inicio", "mas antigua", "antigua", "antiguas"])


# =========================================================
# Intent: Llamadas entrantes (detalle)
# =========================================================
def intent_llamadas_entrantes(con, df_cols: List[str], filters: Optional[Dict[str, Any]] = None, top_n: int = 5000, question: str = ""):
    dt = _qident("Datetime")
    where_extra = _where_from_filters(filters or {}, df_cols)

    voice = _voice_pred(df_cols)
    incoming = _incoming_pred(df_cols)

    extra = ""
    if voice:
        extra += f" AND {voice}"
    if incoming:
        extra += f" AND {incoming}"

    # si el usuario pide "primera", queremos la más antigua
    first = _is_first_request(question)
    order_dir = "ASC" if first else "DESC"

    cols_out = _select_useful_cols(df_cols)
    select_list = ", ".join([_qident("Datetime") + " AS Datetime"] + [_qident(c) for c in cols_out if c != "Datetime"])

    total_sql = f"SELECT COUNT(*) AS n FROM cdr WHERE {dt} IS NOT NULL {where_extra}{extra};"
    total = int(con.execute(total_sql).fetchone()[0])

    sql = f"""
    SELECT {select_list}
    FROM cdr
    WHERE {dt} IS NOT NULL
    {where_extra}
    {extra}
    ORDER BY {dt} {order_dir}
    LIMIT {int(top_n)};
    """
    ev = con.execute(sql).fetchdf()

    if ev is None or ev.empty:
        return {"answer": "No encontré llamadas entrantes con los filtros actuales.", "evidence": ev, "applied_filters": filters or {}}

    shown = len(ev)
    msg_extra = f" (mostrando {shown} de {total})" if total > shown else f" ({shown} registros)"

    if first and int(top_n) == 1:
        pref = "Primera llamada **entrante** (más antigua)"
    elif first:
        pref = "Primeras llamadas **entrantes** (más antiguas)"
    else:
        pref = "Llamadas **entrantes**"

    return {"answer": f"{pref}{msg_extra}.", "evidence": ev, "applied_filters": filters or {}}


# =========================================================
# Intent: Llamadas salientes (detalle)
# =========================================================
def intent_llamadas_salientes(con, df_cols: List[str], filters: Optional[Dict[str, Any]] = None, top_n: int = 5000, question: str = ""):
    dt = _qident("Datetime")
    where_extra = _where_from_filters(filters or {}, df_cols)

    voice = _voice_pred(df_cols)
    outgoing = _outgoing_pred(df_cols)

    extra = ""
    if voice:
        extra += f" AND {voice}"
    if outgoing:
        extra += f" AND {outgoing}"

    first = _is_first_request(question)
    order_dir = "ASC" if first else "DESC"

    cols_out = _select_useful_cols(df_cols)
    select_list = ", ".join([_qident("Datetime") + " AS Datetime"] + [_qident(c) for c in cols_out if c != "Datetime"])

    total_sql = f"SELECT COUNT(*) AS n FROM cdr WHERE {dt} IS NOT NULL {where_extra}{extra};"
    total = int(con.execute(total_sql).fetchone()[0])

    sql = f"""
    SELECT {select_list}
    FROM cdr
    WHERE {dt} IS NOT NULL
    {where_extra}
    {extra}
    ORDER BY {dt} {order_dir}
    LIMIT {int(top_n)};
    """
    ev = con.execute(sql).fetchdf()

    if ev is None or ev.empty:
        return {"answer": "No encontré llamadas salientes con los filtros actuales.", "evidence": ev, "applied_filters": filters or {}}

    shown = len(ev)
    msg_extra = f" (mostrando {shown} de {total})" if total > shown else f" ({shown} registros)"

    if first and int(top_n) == 1:
        pref = "Primera llamada **saliente** (más antigua)"
    elif first:
        pref = "Primeras llamadas **salientes** (más antiguas)"
    else:
        pref = "Llamadas **salientes**"

    return {"answer": f"{pref}{msg_extra}.", "evidence": ev, "applied_filters": filters or {}}
