# core/query_engine.py
# Motor de dataset + DuckDB (solo lectura para consultas)
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import duckdb
import pandas as pd


# -----------------------------
# Helpers: normalización columnas
# -----------------------------
def _norm(s: str) -> str:
    return (s or "").strip().lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")


def _find_col(cols: List[str], options: List[str]) -> Optional[str]:
    low = {_norm(c): c for c in cols}
    for op in options:
        k = _norm(op)
        if k in low:
            return low[k]
    return None


def parse_datetime_flexible(df: pd.DataFrame) -> pd.Series:
    """
    Intenta construir una columna Datetime robusta.
    Soporta:
    - Datetime existente
    - FechaHora en una sola columna
    - Fecha + Hora separadas
    - Detecta variantes comunes por nombres
    """
    cols = list(df.columns)

    dt_col = _find_col(cols, ["Datetime", "DateTime", "fecha_hora", "fechaHora", "FechaHora", "FECHAHORA"])
    if dt_col:
        s = pd.to_datetime(df[dt_col], errors="coerce", dayfirst=True, infer_datetime_format=True)
        return s

    fh_col = _find_col(cols, ["FechaHora", "FECHAHORA", "fecha_hora", "fechaHora"])
    if fh_col:
        s = pd.to_datetime(df[fh_col], errors="coerce", dayfirst=True, infer_datetime_format=True)
        return s

    fecha_col = _find_col(cols, ["Fecha", "FECHA", "date", "Date"])
    hora_col = _find_col(cols, ["Hora", "HORA", "time", "Time"])

    # intento por heurística si no se llaman exacto
    if not fecha_col:
        for c in cols:
            if "fecha" in _norm(c) or "date" in _norm(c):
                fecha_col = c
                break

    if not hora_col:
        for c in cols:
            if "hora" in _norm(c) or "time" in _norm(c):
                hora_col = c
                break

    if fecha_col and hora_col:
        combo = df[fecha_col].astype(str).str.strip() + " " + df[hora_col].astype(str).str.strip()
        s = pd.to_datetime(combo, errors="coerce", dayfirst=True, infer_datetime_format=True)
        return s

    # último recurso: buscar una columna que parezca timestamp
    for c in cols:
        sample = df[c].astype(str).head(30).tolist()
        hits = sum(1 for v in sample if any(x in str(v) for x in [":", "-", "/"]))
        if hits >= 10:
            s = pd.to_datetime(df[c], errors="coerce", dayfirst=True, infer_datetime_format=True)
            # si al menos 30% parseó, lo aceptamos
            if s.notna().mean() >= 0.3:
                return s

    return pd.to_datetime(pd.Series([pd.NaT] * len(df)), errors="coerce")


def ensure_numeric_cols(df: pd.DataFrame) -> pd.DataFrame:
    """
    Asegura que LAT/LON sean numéricas si existen con variantes comunes.
    """
    cols = list(df.columns)
    lat = _find_col(cols, ["LAT", "Lat", "Latitud", "LATITUD", "Latitude"])
    lon = _find_col(cols, ["LON", "Lon", "Longitud", "LONGITUD", "Longitude"])

    if lat:
        df[lat] = pd.to_numeric(df[lat], errors="coerce")
    if lon:
        df[lon] = pd.to_numeric(df[lon], errors="coerce")
    return df


@dataclass
class DatasetState:
    filas: int
    dt_min: Optional[pd.Timestamp]
    dt_max: Optional[pd.Timestamp]
    dt_nulos: int
    tiene_ubicacion: bool
    multi_cdr: bool


class QueryEngine:
    """
    Engine en memoria: guarda DF y lo registra en DuckDB como tabla 'cdr'
    (solo lectura: todo se hace con SELECT).
    """

    def __init__(self) -> None:
        self._df: Optional[pd.DataFrame] = None
        self._con = duckdb.connect(database=":memory:")
        self._registered = False

    @property
    def df(self) -> Optional[pd.DataFrame]:
        return self._df

    @property
    def con(self):
        return self._con

    def load_from_excels(
        self,
        files: List[Tuple[str, BytesIO]],
        titular_by_file: Optional[Dict[str, str]] = None,
    ) -> pd.DataFrame:
        frames: List[pd.DataFrame] = []

        for fname, bio in files:
            bio.seek(0)
            df = pd.read_excel(bio)
            df = df.copy()

            # si no trae "Teléfono" / "Telefono", y el usuario asignó titular, lo ponemos
            cols = list(df.columns)
            tel_col = _find_col(cols, ["Teléfono", "Telefono", "TELEFONO", "titular", "TITULAR"])
            titular = (titular_by_file or {}).get(fname)

            if not tel_col and titular:
                df["Teléfono"] = str(titular).strip()
            elif tel_col and _norm(tel_col) != _norm("Teléfono"):
                # unificamos nombre visual
                df.rename(columns={tel_col: "Teléfono"}, inplace=True)

            # Datetime
            df["Datetime"] = parse_datetime_flexible(df)

            # coords numéricas si existen
            df = ensure_numeric_cols(df)

            # marca origen
            df["_origen_archivo"] = fname

            frames.append(df)

        out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        self.load_dataframe(out)
        return out

    def load_dataframe(self, df: pd.DataFrame) -> None:
        self._df = df.copy()

        # registra / reemplaza tabla cdr
        self._con.unregister("cdr") if self._registered else None
        self._con.register("cdr", self._df)
        self._registered = True

    def get_state(self) -> DatasetState:
        df = self._df
        if df is None or df.empty:
            return DatasetState(0, None, None, 0, False, False)

        dt = df.get("Datetime")
        dt_nulos = int(dt.isna().sum()) if dt is not None else len(df)

        dt_min = pd.to_datetime(dt.min(), errors="coerce") if dt is not None and dt.notna().any() else None
        dt_max = pd.to_datetime(dt.max(), errors="coerce") if dt is not None and dt.notna().any() else None

        cols = list(df.columns)
        lat = _find_col(cols, ["LAT", "Lat", "Latitud", "LATITUD", "Latitude"])
        lon = _find_col(cols, ["LON", "Lon", "Longitud", "LONGITUD", "Longitude"])

        tiene_ubic = False
        if lat and lon:
            tiene_ubic = df[lat].notna().any() and df[lon].notna().any()

        multi = False
        if "Teléfono" in df.columns:
            multi = df["Teléfono"].dropna().astype(str).nunique() > 1

        return DatasetState(
            filas=int(len(df)),
            dt_min=dt_min,
            dt_max=dt_max,
            dt_nulos=dt_nulos,
            tiene_ubicacion=tiene_ubic,
            multi_cdr=multi,
        )
