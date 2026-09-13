# core/agent_validators.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict
import pandas as pd

@dataclass
class ValidationResult:
    ok: bool
    message: str
    details: Dict[str, Any]

def validate_rows(df: pd.DataFrame) -> ValidationResult:
    if df is None:
        return ValidationResult(False, "Sin resultados (df=None).", {})
    if len(df) == 0:
        return ValidationResult(False, "Sin registros que cumplan los filtros.", {"rows": 0})
    return ValidationResult(True, "OK", {"rows": int(len(df))})

def note_location(has_location: bool) -> str:
    if has_location:
        return ("Nota metodológica: ubicación estimada por celda/antena (y sector/azimut si existe). "
                "No equivale a GPS; la precisión depende de cobertura, carga de red y condiciones.")
    return ("Nota metodológica: este dataset no contiene campos de ubicación (antena/lat/lon/dirección).")
