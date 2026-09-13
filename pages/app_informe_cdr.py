# pages/app_informe_cdr.py
# Go Mapper · Generador automático de informe CDR
# Usa como insumo un archivo XLSX limpio generado por la app de Limpieza.

import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")
import pandas as pd
import numpy as np
from io import BytesIO
from datetime import datetime

# 🔐 Guardián central de la suite
from guardian import login_guard
from suite_nav import render_suite_sidebar  # menú lateral de la suite
from ui.styles import apply_theme, page_header, section_title


# --------------------------------------------------------
# Helpers
# --------------------------------------------------------
def find_col(df: pd.DataFrame, candidates):
    """Devuelve el primer nombre de columna que exista en el DataFrame."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def preprocesar_cdr(df: pd.DataFrame):
    """
    Detecta columnas clave y construye una columna '_dt' con la marca temporal.
    Devuelve el DataFrame (con _dt) y un diccionario meta con los nombres de columnas.
    """
    meta = {}
    meta["telefono_col"] = find_col(df, ["Teléfono", "Telefono", "MSISDN", "Linea", "Línea"])
    meta["tipo_col"] = find_col(df, ["Tipo", "TIPO", "tipo"])
    meta["numA_col"] = find_col(df, ["Número A", "Numero A", "NUMERO A", "A", "MSISDN_A", "Numero_A"])
    meta["numB_col"] = find_col(df, ["Número B", "Numero B", "NUMERO B", "B", "MSISDN_B", "Numero_B"])
    meta["fecha_col"] = find_col(df, ["Fecha", "FECHA", "fecha"])
    meta["hora_col"] = find_col(df, ["Hora", "HORA", "hora"])
    meta["datetime_col"] = find_col(df, ["Datetime", "DATETIME", "datetime"])
    meta["lat_col"] = find_col(df, ["Latitud", "LATITUD", "lat", "LAT"])
    meta["lon_col"] = find_col(df, ["Longitud", "LONGITUD", "lon", "LON"])
    meta["imei_col"] = find_col(df, ["IMEI", "imei"])

    # Construcción de marca temporal
    if meta["datetime_col"] and meta["datetime_col"] in df.columns:
        df["_dt"] = pd.to_datetime(df[meta["datetime_col"]], errors="coerce")
    elif meta["fecha_col"] and meta["hora_col"]:
        df["_dt"] = pd.to_datetime(
            df[meta["fecha_col"]].astype(str) + " " + df[meta["hora_col"]].astype(str),
            errors="coerce",
            dayfirst=True,
        )
    else:
        raise ValueError(
            "No se encontró columna de fecha/hora ni 'Datetime' en el archivo limpio. "
            "Verifica que provenga del módulo de Limpieza."
        )

    if df["_dt"].isna().all():
        raise ValueError("No fue posible interpretar las fechas/horas del archivo.")

    return df, meta


def build_report_text(df: pd.DataFrame, meta: dict, numero_objeto: str) -> str:
    """
    Construye el texto del informe a partir del DataFrame limpio y el número objeto.
    Solo usa información del CDR (sin OSINT).
    """
    tipo_col = meta.get("tipo_col")
    numA_col = meta.get("numA_col")
    numB_col = meta.get("numB_col")
    lat_col = meta.get("lat_col")
    lon_col = meta.get("lon_col")

    # Asegurar tipos string donde convenga
    if tipo_col and tipo_col in df.columns:
        df[tipo_col] = df[tipo_col].astype(str)

    # Fechas básicas
    dt_valid = df["_dt"].dropna()
    periodo_inicio = dt_valid.min()
    periodo_fin = dt_valid.max()
    total_eventos = len(df)

    # Distribución por fecha y por hora
    eventos_por_fecha = dt_valid.dt.date.value_counts().sort_index()
    num_dias = eventos_por_fecha.shape[0]
    promedio_diario = round(total_eventos / num_dias, 1) if num_dias > 0 else None

    eventos_por_hora = dt_valid.dt.hour.value_counts().sort_index()
    if not eventos_por_hora.empty:
        hora_pico = int(eventos_por_hora.idxmax())
        eventos_hora_pico = int(eventos_por_hora.max())
    else:
        hora_pico = None
        eventos_hora_pico = None

    # Resumen por tipo de evento
    if tipo_col and tipo_col in df.columns:
        vc_tipos = df[tipo_col].value_counts()
        if not vc_tipos.empty:
            lineas_tipos = [f"- {t}: {int(c)} eventos" for t, c in vc_tipos.items()]
            resumen_tipos_txt = "\n".join(lineas_tipos)
        else:
            resumen_tipos_txt = (
                "La columna de tipo existe pero no se encontraron eventos válidos para clasificar."
            )
    else:
        resumen_tipos_txt = (
            "El archivo limpio no contiene una columna de tipo de evento identificable; "
            "por lo tanto, el análisis se refiere al total de eventos sin desagregar por servicio."
        )

    # Contactos frecuentes (si tenemos Número A/B)
    top_contactos_txt = ""
    top_noche_txt = ""
    if numA_col and numB_col and numA_col in df.columns and numB_col in df.columns:
        df_ct = df.copy()
        df_ct[numA_col] = df_ct[numA_col].astype(str)
        df_ct[numB_col] = df_ct[numB_col].astype(str)
        numero_objeto_str = str(numero_objeto)

        df_ct["_contacto"] = np.where(
            df_ct[numA_col] == numero_objeto_str,
            df_ct[numB_col],
            df_ct[numA_col],
        )
        # Quitar autorreferencias
        df_ct = df_ct[df_ct["_contacto"] != numero_objeto_str]

        top_contactos = df_ct["_contacto"].value_counts().head(10)
        if not top_contactos.empty:
            lineas = []
            for i, (num, cnt) in enumerate(top_contactos.items(), start=1):
                lineas.append(f"{i}. {num} — {int(cnt)} eventos")
            top_contactos_txt = "\n".join(lineas)
        else:
            top_contactos_txt = (
                "No se identificaron contactos frecuentes distintos a la propia línea en el periodo analizado."
            )

        # Contactos nocturnos (22:00–05:00)
        df_noche = df_ct[(df_ct["_dt"].dt.hour >= 22) | (df_ct["_dt"].dt.hour < 5)]
        top_noche = df_noche["_contacto"].value_counts().head(5)
        if not top_noche.empty:
            lineas_noche = []
            for i, (num, cnt) in enumerate(top_noche.items(), start=1):
                lineas_noche.append(f"{i}. {num} — {int(cnt)} eventos nocturnos")
            top_noche_txt = "\n".join(lineas_noche)
        else:
            top_noche_txt = (
                "No se observaron contactos relevantes en la franja nocturna (22:00–05:00)."
            )
    else:
        top_contactos_txt = (
            "El archivo limpio no contiene columnas claras de 'Número A' y 'Número B', "
            "por lo que no es posible identificar contactos frecuentes."
        )
        top_noche_txt = ""

    # Georreferencias recurrentes y zona de pernocta
    top_geo_txt = ""
    pernocta_txt = ""
    if lat_col and lon_col and lat_col in df.columns and lon_col in df.columns:
        df_geo = df.dropna(subset=[lat_col, lon_col]).copy()
        if not df_geo.empty:
            df_geo[lat_col] = pd.to_numeric(df_geo[lat_col], errors="coerce")
            df_geo[lon_col] = pd.to_numeric(df_geo[lon_col], errors="coerce")
            df_geo = df_geo.dropna(subset=[lat_col, lon_col])

        if not df_geo.empty:
            geo_counts = (
                df_geo.groupby([lat_col, lon_col])
                .size()
                .reset_index(name="eventos")
                .sort_values("eventos", ascending=False)
            )
            top_geo = geo_counts.head(3)

            lineas_geo = []
            for _, row in top_geo.iterrows():
                lat = float(row[lat_col])
                lon = float(row[lon_col])
                cnt = int(row["eventos"])
                gmaps = f"https://maps.google.com/?q={lat},{lon}"
                lineas_geo.append(f"- ({lat:.6f}, {lon:.6f}) — {cnt} eventos · {gmaps}")
            top_geo_txt = "\n".join(lineas_geo)

            # Zona de pernocta: geos en horario 22–05
            df_geo_noche = df_geo[(df_geo["_dt"].dt.hour >= 22) | (df_geo["_dt"].dt.hour < 5)]
            if not df_geo_noche.empty:
                pernocta_counts = (
                    df_geo_noche.groupby([lat_col, lon_col])
                    .size()
                    .reset_index(name="eventos")
                    .sort_values("eventos", ascending=False)
                )
                top_pernocta = pernocta_counts.iloc[0]
                lat_p = float(top_pernocta[lat_col])
                lon_p = float(top_pernocta[lon_col])
                cnt_p = int(top_pernocta["eventos"])
                pernocta_txt = (
                    "La zona con mayor recurrencia nocturna (22:00–05:00) "
                    f"se ubica aproximadamente en ({lat_p:.6f}, {lon_p:.6f}), "
                    f"con {cnt_p} eventos registrados en dicho horario."
                )
            else:
                pernocta_txt = (
                    "Con la información disponible no se identificó una zona de pernocta "
                    "claramente predominante en la franja 22:00–05:00."
                )
        else:
            top_geo_txt = (
                "El archivo limpio contiene columnas de coordenadas, "
                "pero no se encontraron registros con latitud/longitud utilizables."
            )
    else:
        top_geo_txt = (
            "El archivo limpio no contiene columnas de latitud y longitud, "
            "por lo que no es posible estimar zonas de recurrencia geográfica."
        )

    # Texto del informe
    periodo_inicio_txt = periodo_inicio.strftime("%d/%m/%Y") if isinstance(periodo_inicio, datetime) else "N/D"
    periodo_fin_txt = periodo_fin.strftime("%d/%m/%Y") if isinstance(periodo_fin, datetime) else "N/D"

    if promedio_diario is not None:
        promedio_txt = f"un promedio aproximado de {promedio_diario} eventos por día."
    else:
        promedio_txt = "una distribución diaria que no pudo estimarse con precisión."

    if hora_pico is not None:
        hora_pico_txt = (
            f"La hora con mayor concentración de eventos fue alrededor de las {hora_pico:02d}:00 "
            f"(con aproximadamente {eventos_hora_pico} registros en esa franja)."
        )
    else:
        hora_pico_txt = (
            "No se identificó una hora del día claramente predominante en cuanto al volumen de eventos."
        )

    reporte = f"""
GO MAPPER · INFORME DE ANÁLISIS DE REGISTROS DE COMUNICACIÓN

1. ANTECEDENTES Y OBJETO DEL ANÁLISIS
Se analizó la información de tráfico telefónico asociada a la línea {numero_objeto}, 
proporcionada en formato de registros de detalle de llamadas (CDR) previamente procesados 
mediante el módulo de Limpieza de la Suite Go Mapper.

El periodo comprendido en los registros va del {periodo_inicio_txt} al {periodo_fin_txt}, 
con un total de {total_eventos} eventos de red (llamadas de voz, mensajes y tráfico de datos), 
de acuerdo con el archivo limpio proporcionado.

El objeto de este informe es describir, a nivel descriptivo y analítico, los patrones básicos 
de uso de la línea, los contactos con mayor recurrencia y las zonas geográficas donde se 
concentran las comunicaciones, con base únicamente en la información contenida en el CDR.

2. METODOLOGÍA

2.1 Normalización y depuración
• Se utilizó el archivo XLSX limpio proveniente del módulo de Limpieza de Go Mapper, 
  en el que se unificaron formatos de fecha y hora, tipos de evento y coordenadas geográficas, 
  así como la depuración de registros de tráfico de datos redundantes.
• La fecha y hora de cada registro se integraron en un solo campo de marca temporal, 
  permitiendo el análisis cronológico y por franjas horarias.

2.2 Criterios de análisis
• Se consideró como “línea objeto” el número {numero_objeto}.
• Los eventos se clasificaron por tipo de servicio de acuerdo con la columna de tipo del archivo limpio.
• Se calcularon frecuencias absolutas por día y hora, identificando picos de actividad.
• Cuando fue posible, se identificaron contactos frecuentes a partir de la relación entre Número A y Número B.
• Cuando existieron coordenadas, se agruparon los eventos por latitud/longitud para estimar zonas de recurrencia.

3. RESULTADOS ESTADÍSTICOS BÁSICOS

En el periodo analizado se registraron {total_eventos} eventos asociados a la línea {numero_objeto}, 
con {promedio_txt}

Resumen por tipo de evento (según columna de tipo del archivo limpio):

{resumen_tipos_txt}

Respecto a la distribución temporal:

{hora_pico_txt}

4. CONTACTOS FRECUENTES (SEGÚN CDR)

A partir de los valores de Número A y Número B, considerando como línea objeto el número {numero_objeto}, 
se identificaron los siguientes contactos con mayor número de eventos (llamadas, mensajes y/o otros 
registros en los que participa la línea):

{top_contactos_txt}

En la franja nocturna (22:00–05:00) se observaron los siguientes contactos más frecuentes:

{top_noche_txt}

5. ZONAS DE RECURRENCIA GEOGRÁFICA

Con base en las coordenadas de latitud y longitud presentes en el archivo limpio, se calcularon 
las posiciones con mayor número de eventos asociados a la línea analizada.

Principales puntos de recurrencia (ordenados de mayor a menor frecuencia):

{top_geo_txt}

{pernocta_txt}

6. SÍNTESIS INTERPRETATIVA (NIVEL DESCRIPTIVO)

Con la información disponible en el CDR limpio se pueden señalar, de manera descriptiva, los siguientes aspectos:

• La línea {numero_objeto} presenta un volumen total de {total_eventos} eventos en el periodo estudiado, 
  con actividad repartida a lo largo de varios días y con picos horarios específicos.
• La clasificación por tipo de evento permite distinguir los diferentes usos del servicio 
  (llamadas de voz, mensajes, tráfico de datos, etc.), lo que puede orientar el análisis del patrón de uso.
• Los contactos frecuentes identificados a partir de los campos de Número A y Número B representan 
  aquellos números con los que la línea mantiene mayor interacción cuantitativa.
• Cuando se dispone de coordenadas geográficas, las zonas de mayor recurrencia y, en su caso, la zona de 
  mayor actividad nocturna, pueden ser indicativas de lugares de estancia habitual, trabajo, residencia 
  o tránsito frecuente, sin que ello implique por sí mismo una correspondencia directa con un domicilio 
  concreto u otra referencia específica.

Este informe constituye un borrador técnico basado exclusivamente en la información contenida en el CDR 
y en el procesamiento realizado por la Suite Go Mapper. Corresponde al perito o analista que lo utilice 
vincular estos resultados con otros elementos de información del caso (entrevistas, inspecciones, 
documentos, OSINT u otros medios de prueba) y emitir, en su caso, las conclusiones periciales formales 
que procedan.
""".strip()

    return reporte


def build_docx_from_text(text: str):
    """
    Construye un DOCX simple a partir del texto del informe.
    Devuelve un BytesIO listo para descargar, o None si no está instalada python-docx.
    """
    try:
        from docx import Document  # type: ignore
    except ImportError:
        return None

    doc = Document()
    # Separar por bloques de párrafos (doble salto de línea)
    for block in text.split("\n\n"):
        doc.add_paragraph(block)

    bio = BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio


# --------------------------------------------------------
# APP PRINCIPAL
# --------------------------------------------------------
def main():
    # Guard de login + menú lateral de la suite
    login_guard()
    render_suite_sidebar()
    apply_theme()

    page_header(
        "Generador de Informe CDR",
        "Construye un borrador técnico a partir de un archivo limpio, conservando el análisis basado únicamente en el CDR cargado.",
        eyebrow="INFORME PERICIAL",
        badges=["Texto editable", "DOCX opcional", "Resumen técnico"],
    )

    st.markdown(
        """
Esta herramienta toma como insumo un **archivo XLSX limpio** generado por el módulo de **Limpieza** 
de la Suite Go Mapper y construye un **borrador de informe** de análisis de CDR.

👉 El informe **solo usa información del propio CDR** (no incluye OSINT, fotos de perfil ni datos externos).
"""
    )

    uploaded_file = st.file_uploader(
        "Sube el archivo limpio (XLSX) de la línea que deseas analizar",
        type=["xlsx", "xls"],
    )

    if not uploaded_file:
        return

    # Leer archivo limpio
    try:
        df = pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"No se pudo leer el archivo: {e}")
        return

    st.success(f"Archivo cargado correctamente con {len(df):,} registros.")

    # Preprocesar y detectar columnas
    try:
        df, meta = preprocesar_cdr(df)
    except Exception as e:
        st.error(f"Error al preparar el archivo limpio: {e}")
        return

    telefono_col = meta.get("telefono_col")
    numA_col = meta.get("numA_col")
    numB_col = meta.get("numB_col")

    # Selección de la línea objeto
    section_title("Configuración", "Define la línea objeto y genera el borrador del informe.", "01")
    with st.expander("Configuración de la línea objeto de análisis", expanded=True):
        numero_objeto = None

        if telefono_col and telefono_col in df.columns:
            opciones = sorted(df[telefono_col].dropna().astype(str).unique())
            if len(opciones) == 0:
                st.warning(
                    "No se encontraron valores en la columna de teléfono; "
                    "puedes especificar el número manualmente."
                )
            else:
                numero_objeto = st.selectbox(
                    "Selecciona la línea objeto de análisis", opciones
                )
        else:
            st.info(
                "El archivo no trae una columna clara de 'Teléfono' o línea objeto. "
                "Puedes escribirla manualmente."
            )

        numero_manual = st.text_input(
            "Número a considerar como línea objeto (si deseas sobrescribir la selección anterior):",
            value=numero_objeto or "",
        ).strip()

        if numero_manual:
            numero_objeto = numero_manual

        if not numero_objeto:
            st.error("Es necesario especificar la línea objeto para continuar con el análisis.")
            return

    # Botón de generación
    if st.button("Generar informe", type="primary"):
        with st.spinner("Generando borrador de informe a partir del archivo limpio..."):
            reporte_texto = build_report_text(df, meta, numero_objeto)

        section_title("Vista previa del informe", "Revisa el texto antes de exportar o copiar al expediente.", "02")
        st.text_area("Informe generado", value=reporte_texto, height=600)

        # Descarga como TXT
        txt_bytes = reporte_texto.encode("utf-8")
        st.download_button(
            "⬇️ Descargar informe en TXT",
            data=txt_bytes,
            file_name=f"informe_cdr_{numero_objeto}.txt",
            mime="text/plain",
        )

        # Descarga opcional como DOCX (si existe python-docx)
        docx_buffer = build_docx_from_text(reporte_texto)
        if docx_buffer is not None:
            st.download_button(
                "⬇️ Descargar informe en DOCX",
                data=docx_buffer,
                file_name=f"informe_cdr_{numero_objeto}.docx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
            )
        else:
            st.info(
                "Si deseas exportar directamente a Word (DOCX), instala la librería "
                "`python-docx` en el entorno de la Suite."
            )


if __name__ == "__main__":
    main()
