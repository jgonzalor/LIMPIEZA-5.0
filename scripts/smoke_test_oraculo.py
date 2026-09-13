# scripts/smoke_test_oraculo.py
"""
Smoke test local (sin Streamlit):
- Carga un Excel limpio
- Construye DuckDB
- Ejecuta 6 preguntas típicas y muestra respuesta + filas devueltas

Uso:
  python scripts/smoke_test_oraculo.py /ruta/a/tu_cdr_limpia.xlsx
"""
from __future__ import annotations

import sys, os
import pandas as pd
from datetime import datetime

# Ajusta el path si lo ejecutas desde repo raíz
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from core.query_engine import QueryEngine
from core.agent_orchestrator import CDROracleAgentV2

def main(xlsx: str):
    df = pd.read_excel(xlsx)
    case_dir = ".mapper_cases/SMOKE"
    db_path = os.path.join(case_dir, "cdr_limpia.duckdb")
    eng = QueryEngine(db_path)
    prof = eng.load_cdr_dataframes([df], titulares=[None], table="cdr")
    agent = CDROracleAgentV2(eng, case_dir=case_dir, table="cdr")

    questions = [
        "resumen del dataset",
        "conteo por tipo",
        "top 10 más frecuentes",
        "última llamada entrante",
        "eventos el 23/04/2024 22:15",
        "de 21:00 a 02:00 del 01/04/2024 al 30/04/2024",
    ]

    for q in questions:
        r = agent.answer(q)
        print("\n===", q)
        print("intent:", r.intent)
        print("answer:", r.answer)
        print("rows:", len(r.evidence))
        if len(r.evidence):
            print(r.evidence.head(3).to_string(index=False))

    eng.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Pasa un .xlsx como argumento.")
        sys.exit(2)
    main(sys.argv[1])
