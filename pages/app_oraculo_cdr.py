# pages/app_consulta_inteligente.py
# 🧠 ORÁCULO CDR v2 — Consulta Inteligente (MAPPER)
# Pregunta -> intent -> SELECT (solo lectura) -> respuesta + evidencia + filtros

from __future__ import annotations

from io import BytesIO
from typing import Dict, List, Tuple
import io
from datetime import datetime as dt

import pandas as pd
import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")
from ui.styles import apply_theme, page_header, section_title

from core.query_engine import QueryEngine
from core.agent_orchestrator import run_question
from core.agent_intents_registry import INTENTS


# (Opcional) Integración Suite: si existe, úsala; si no, no revienta.
try:
    from guardian import login_guard
except Exception:
    login_guard = None

try:
    from suite_nav import render_suite_sidebar
except Exception:
    render_suite_sidebar = None


# -----------------------------
# Helpers UI/Compat
# -----------------------------
def _fmt_ts(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    try:
        return pd.to_datetime(x).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(x)


def _get_engine() -> QueryEngine:
    if "qe_oraculo" not in st.session_state:
        st.session_state["qe_oraculo"] = QueryEngine()
    return st.session_state["qe_oraculo"]


def _container_with_border():
    # Compatibilidad: Streamlit viejo no soporta st.container(border=True)
    try:
        return st.container(border=True)
    except TypeError:
        return st.container()


def _dataframe_safe(df: pd.DataFrame):
    # Compatibilidad: Streamlit viejo no soporta hide_index
    try:
        st.dataframe(df, use_container_width=True, hide_index=True)
    except TypeError:
        st.dataframe(df, use_container_width=True)


def _metric_safe(label: str, value: str):
    # Compatibilidad: por si st.metric no existe (muy raro, pero por si acaso)
    if hasattr(st, "metric"):
        st.metric(label, value)
    else:
        st.write(f"**{label}:** {value}")


def _to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def _to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Evidencia")
    bio.seek(0)
    return bio.read()


def _push_log(question: str, intent: str, answer: str, n_rows: int, filters: dict):
    if "oraculo_log" not in st.session_state:
        st.session_state["oraculo_log"] = []
    st.session_state["oraculo_log"].append({
        "ts": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "question": question,
        "intent": intent,
        "rows": int(n_rows),
        "filters": filters or {},
        "answer": str(answer)[:5000],
    })
    # recorta log para que no crezca infinito
    if len(st.session_state["oraculo_log"]) > 50:
        st.session_state["oraculo_log"] = st.session_state["oraculo_log"][-50:]


def main():
    pass  # Page configuration is initialized before rendering.

    # seguridad suite (si aplica)
    if login_guard:
        login_guard()

    # sidebar suite (si aplica)
    if render_suite_sidebar:
        render_suite_sidebar()
    apply_theme()

    page_header(
        "ORÁCULO CDR",
        "Consulta inteligente de CDR limpio: pregunta, intención detectada, respuesta estructurada y filas de evidencia exportables.",
        eyebrow="CONSULTA ASISTIDA",
        badges=["DuckDB en memoria", "Solo lectura", "Evidencia exportable"],
    )

    qe = _get_engine()

    # =========================================================
    #  HEADER SUPERIOR: CARGA + ESTADO + OPCIONES (NO SIDEBAR)
    # =========================================================
    with _container_with_border():
        col_left, col_right = st.columns([1.35, 1.0])

        # -----------------------------
        # Izquierda: Caso + Carga dataset
        # -----------------------------
        with col_left:
            section_title("Carga de CDR limpia", "Sube uno o varios Excel limpios y registra el nombre del caso.", "01")

            case_name = st.text_input(
                "Nombre del caso",
                value=st.session_state.get("case_name", "Caso_001"),
            )
            st.session_state["case_name"] = case_name

            files_up = st.file_uploader(
                "Sube 1 o varios Excel (CDR limpia)",
                type=["xlsx", "xls"],
                accept_multiple_files=True,
            )

            titular_by_file: Dict[str, str] = {}

            if files_up:
                st.info("Si subes varios archivos y NO traen columna 'Teléfono', asigna el titular a cada archivo.")
                with st.expander("Asignar titular por archivo (opcional)", expanded=True):
                    for f in files_up:
                        key = f"titular_{f.name}"
                        titular_by_file[f.name] = st.text_input(
                            f"Titular para: {f.name}",
                            value=st.session_state.get(key, ""),
                            key=key,
                        )

            btn_load = st.button(
                "✅ Cargar/Actualizar dataset",
                use_container_width=True,
                disabled=not bool(files_up),
            )

            if btn_load:
                excel_blobs: List[Tuple[str, BytesIO]] = []
                for f in files_up or []:
                    excel_blobs.append((f.name, BytesIO(f.getvalue())))
                qe.load_from_excels(excel_blobs, titular_by_file=titular_by_file)
                st.success("Dataset cargado/actualizado.")

        # -----------------------------
        # Derecha: Estado + forzar intent
        # -----------------------------
        with col_right:
            section_title("Estado del dataset", "Resumen operativo del conjunto cargado.", "02")
            state = qe.get_state()

            st.write(f"**Filas:** {state.filas}")
            st.write(f"**Rango:** {_fmt_ts(state.dt_min)} → {_fmt_ts(state.dt_max)}")
            st.write(f"**Datetime nulos:** {state.dt_nulos}")
            st.write(f"**Ubicación:** {'Sí' if state.tiene_ubicacion else 'No'}")
            st.write(f"**Multi-CDR:** {'Sí' if state.multi_cdr else 'No'}")

            st.markdown("---")
            section_title("Pruebas / forzar intent", "Herramienta de control para validar clasificación.", "03")
            forced = st.selectbox(
                "Forzar intent (opcional)",
                options=["(auto)"] + list(INTENTS.keys()),
                index=0,
            )
            st.caption("Útil para pruebas cuando la clasificación no sea la esperada.")

    # =========================================================
    #  CONSULTA
    # =========================================================
    section_title("Consulta", "Formula preguntas operativas y revisa la evidencia de soporte.", "04")

    colA, colB = st.columns([2, 1])

    with colA:
        question = st.text_input("Pregunta", value="dame la ubicacion mas frecuente")

        with st.expander("Filtros (opcional)", expanded=False):
            f_tel = st.text_input("Teléfono (titular) exacto", value="")
            f_from = st.text_input("Desde (YYYY-MM-DD HH:MM:SS)", value="")
            f_to = st.text_input("Hasta (YYYY-MM-DD HH:MM:SS)", value="")

        filters = {}
        if f_tel.strip():
            filters["telefono"] = f_tel.strip()
        if f_from.strip():
            filters["date_from"] = f_from.strip()
        if f_to.strip():
            filters["date_to"] = f_to.strip()

        run = st.button("Preguntar", use_container_width=False)

    with colB:
        st.markdown("### 💡 Ejemplos")
        st.write("- dame la ubicación más frecuente")
        st.write("- top 10 ubicaciones más repetidas")
        st.write("- latitud y longitud más repetida")
        st.write("- dame las últimas 20 llamadas")
        st.write("- dame todas las llamadas entrantes")
        st.write("- dame la primer llamada entrante")

    # =========================================================
    #  RESULTADO PRO
    # =========================================================
    st.markdown("---")
    st.markdown("## 🧾 Resultado")

    if run:
        if qe.df is None or qe.df.empty:
            st.error("Primero carga un dataset.")
            return

        df_cols = list(qe.df.columns)
        result = run_question(
            qe.con,
            df_cols,
            question=question,
            forced_intent=forced,
            filters=filters,
        )

        intent = result.get("intent", "—")
        answer = result.get("answer", "—")
        applied = result.get("applied_filters", {}) or {}
        ev = result.get("evidence")

        # KPIs calculados sobre evidencia
        n_rows = int(len(ev)) if isinstance(ev, pd.DataFrame) else 0

        ev_dt_min = None
        ev_dt_max = None
        if isinstance(ev, pd.DataFrame) and not ev.empty and "Datetime" in ev.columns:
            try:
                ev_dt_min = ev["Datetime"].min()
                ev_dt_max = ev["Datetime"].max()
            except Exception:
                ev_dt_min, ev_dt_max = None, None

        _push_log(question=question, intent=intent, answer=answer, n_rows=n_rows, filters=applied)

        # ---- Tarjeta de Resumen + KPIs ----
        with _container_with_border():
            st.markdown("### 📌 Resumen ejecutivo")
            k1, k2, k3, k4 = st.columns(4)
            with k1:
                _metric_safe("Intent", str(intent))
            with k2:
                _metric_safe("Registros", str(n_rows))
            with k3:
                _metric_safe("Desde", _fmt_ts(ev_dt_min))
            with k4:
                _metric_safe("Hasta", _fmt_ts(ev_dt_max))

            st.markdown(f"**Pregunta:** {question}")
            st.markdown(f"**Respuesta:** {answer}")

        # ---- Tabs (si existen) / Fallback a expanders ----
        has_tabs = hasattr(st, "tabs")

        if has_tabs:
            tab1, tab2, tab3, tab4 = st.tabs(["Resumen", "Evidencia", "Descarga", "Filtros/Bitácora"])

            with tab1:
                st.write(f"**Intent detectado:** `{intent}`")
                st.write(f"**Respuesta:** {answer}")

                if isinstance(ev, pd.DataFrame) and not ev.empty:
                    st.markdown("**Vista rápida (primeras 10 filas):**")
                    _dataframe_safe(ev.head(10))
                else:
                    st.info("Sin evidencia tabular para mostrar.")

            with tab2:
                if not isinstance(ev, pd.DataFrame) or ev.empty:
                    st.info("Sin evidencia tabular para mostrar.")
                else:
                    # control de tamaño
                    size = st.selectbox("Mostrar", [50, 100, 500, 1000, "Todo (cuidado)"], index=1)
                    if size == "Todo (cuidado)":
                        if len(ev) > 5000:
                            st.warning("La evidencia es muy grande para renderizar completa. Muestro 5000 filas. Usa Descarga para obtener todo.")
                            view = ev.head(5000)
                        else:
                            view = ev
                    else:
                        view = ev.head(int(size))

                    _dataframe_safe(view)

            with tab3:
                if not isinstance(ev, pd.DataFrame) or ev.empty:
                    st.info("No hay evidencia para descargar.")
                else:
                    csv_bytes = _to_csv_bytes(ev)
                    xlsx_bytes = _to_xlsx_bytes(ev)

                    # Compatibilidad: download_button suele existir, pero por si acaso
                    if hasattr(st, "download_button"):
                        st.download_button(
                            "⬇️ Descargar CSV (evidencia)",
                            data=csv_bytes,
                            file_name=f"{st.session_state.get('case_name','Caso')}_{intent}_evidencia.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )
                        st.download_button(
                            "⬇️ Descargar XLSX (evidencia)",
                            data=xlsx_bytes,
                            file_name=f"{st.session_state.get('case_name','Caso')}_{intent}_evidencia.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )
                    else:
                        st.info("Tu Streamlit no soporta download_button. Actualiza Streamlit o exporta manualmente.")
                        st.code(ev.head(50).to_csv(index=False), language="text")

            with tab4:
                st.markdown("### 🎯 Filtros aplicados")
                st.json(applied)

                st.markdown("### 🧾 Bitácora (últimas consultas)")
                logs = st.session_state.get("oraculo_log", [])
                if logs:
                    df_log = pd.DataFrame(logs)
                    _dataframe_safe(df_log.tail(10))
                else:
                    st.info("Aún no hay bitácora.")

        else:
            # Fallback sin tabs: todo en expanders
            with st.expander("Resumen", expanded=True):
                st.write(f"**Intent detectado:** `{intent}`")
                st.write(f"**Respuesta:** {answer}")
                if isinstance(ev, pd.DataFrame) and not ev.empty:
                    st.markdown("**Vista rápida (primeras 10 filas):**")
                    _dataframe_safe(ev.head(10))
                else:
                    st.info("Sin evidencia tabular para mostrar.")

            with st.expander("Evidencia", expanded=True):
                if not isinstance(ev, pd.DataFrame) or ev.empty:
                    st.info("Sin evidencia tabular para mostrar.")
                else:
                    size = st.selectbox("Mostrar", [50, 100, 500, 1000, "Todo (cuidado)"], index=1)
                    if size == "Todo (cuidado)":
                        if len(ev) > 5000:
                            st.warning("Evidencia muy grande. Muestro 5000 filas. Usa Descarga para obtener todo.")
                            view = ev.head(5000)
                        else:
                            view = ev
                    else:
                        view = ev.head(int(size))
                    _dataframe_safe(view)

            with st.expander("Descarga", expanded=False):
                if not isinstance(ev, pd.DataFrame) or ev.empty:
                    st.info("No hay evidencia para descargar.")
                else:
                    csv_bytes = _to_csv_bytes(ev)
                    xlsx_bytes = _to_xlsx_bytes(ev)

                    if hasattr(st, "download_button"):
                        st.download_button(
                            "⬇️ Descargar CSV (evidencia)",
                            data=csv_bytes,
                            file_name=f"{st.session_state.get('case_name','Caso')}_{intent}_evidencia.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )
                        st.download_button(
                            "⬇️ Descargar XLSX (evidencia)",
                            data=xlsx_bytes,
                            file_name=f"{st.session_state.get('case_name','Caso')}_{intent}_evidencia.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )
                    else:
                        st.info("Tu Streamlit no soporta download_button. Actualiza Streamlit o exporta manualmente.")
                        st.code(ev.head(50).to_csv(index=False), language="text")

            with st.expander("Filtros/Bitácora", expanded=False):
                st.markdown("### 🎯 Filtros aplicados")
                st.json(applied)

                st.markdown("### 🧾 Bitácora (últimas consultas)")
                logs = st.session_state.get("oraculo_log", [])
                if logs:
                    df_log = pd.DataFrame(logs)
                    _dataframe_safe(df_log.tail(10))
                else:
                    st.info("Aún no hay bitácora.")


if __name__ == "__main__":
    main()
