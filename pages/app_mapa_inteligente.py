"""Operational antenna map with explicit field mapping and evidence export."""
from io import BytesIO
import pandas as pd
import streamlit.components.v1 as components
import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")
from guardian import login_guard
from suite_nav import render_suite_sidebar
from ui.components import render_page_header,render_kpi_row
from core.datetime_utils import parse_local_datetime
from core.map_engine import aggregate_antennas, render_map_html

pass  # Page configuration is initialized before rendering.
login_guard('Mapa Inteligente')
render_suite_sidebar()
render_page_header('Mapa Inteligente','Antenas observadas, frecuencia de eventos y filas de soporte en una vista geográfica.',tags=['CDR limpio','Filtros','Exportación'])
with st.expander('Cargar CDR procesado', expanded=not bool(st.session_state.get('gm_map_upload'))):
    file = st.file_uploader('CDR procesado',type=['xlsx','csv'],key='gm_map_upload')
if not file:
    st.info('Carga el Excel de Limpieza para explorar sus antenas. Cada punto representa una coordenada registrada, no la posición exacta del dispositivo.')
    st.stop()
try:
    if file.name.lower().endswith('.csv'):
        data = pd.read_csv(file,dtype=str)
    else:
        xls = pd.ExcelFile(file)
        sheet = st.selectbox('Hoja',xls.sheet_names,index=xls.sheet_names.index('Datos_Limpios') if 'Datos_Limpios' in xls.sheet_names else 0)
        data = pd.read_excel(xls,sheet_name=sheet,dtype=str)
except Exception as error:
    st.error(f'No se pudo leer el archivo: {error}')
    st.stop()
columns = list(data.columns)
if len(columns)<2:
    st.warning('Se requieren columnas de latitud y longitud.')
    st.stop()
with st.expander('Columnas y filtros',expanded=False):
    a,b,c,d = st.columns(4)
    lat = a.selectbox('Latitud',columns,index=columns.index('Latitud') if 'Latitud' in columns else 0)
    lon = b.selectbox('Longitud',columns,index=columns.index('Longitud') if 'Longitud' in columns else 1)
    dt = c.selectbox('Fecha y hora',['Sin columna']+columns,index=columns.index('Datetime')+1 if 'Datetime' in columns else 0)
    kind = d.selectbox('Tipo',['Sin columna']+columns,index=columns.index('Tipo')+1 if 'Tipo' in columns else 0)
    if lat == lon:
        st.warning('Selecciona columnas distintas para latitud y longitud.')
        st.stop()
    data['archivo_origen'] = file.name
    data['fila_excel'] = data.index+2
    if kind != 'Sin columna':
        options = sorted(data[kind].dropna().unique())
        selected = st.multiselect('Eventos',options,default=options)
        data = data[data[kind].isin(selected)]
    if dt != 'Sin columna':
        times = data[dt].map(parse_local_datetime)
        valid_times = times.dropna()
        if not valid_times.empty:
            dates = st.date_input('Periodo',value=(valid_times.min().date(),valid_times.max().date()),key='gm_map_dates')
            keep_unknown = st.checkbox('Incluir eventos sin fecha válida',value=True)
            if len(dates)==2:
                mask = times.dt.date.between(dates[0],dates[1])
                if keep_unknown:
                    mask |= times.isna()
                data = data[mask]
        else:
            st.caption('Sin fechas interpretables: se muestran los eventos seleccionados sin filtro temporal.')
clean, antennas, invalid = aggregate_antennas(data,lat,lon)
render_kpi_row([{'label':'Eventos con coordenadas','value':len(clean)}, {'label':'Antenas / coordenadas','value':len(antennas)}, {'label':'Coordenadas no utilizables','value':invalid}],columns=3)
if antennas.empty:
    st.warning('No hay coordenadas decimales válidas con estos filtros. Revisa las columnas o procesa el archivo en Limpieza.')
    st.stop()
if len(antennas)>20000:
    st.warning('Reduce el periodo para visualizar hasta 20,000 coordenadas. La exportación conserva toda la selección.')
else:
    components.html(render_map_html(antennas), height=675, scrolling=False)
    st.caption('El tamaño representa frecuencia de eventos, no alcance de cobertura. El mapa base requiere internet; no se realiza geocodificación.')
selection = st.selectbox('Detalle de antena',[None]+list(antennas.index),format_func=lambda i:'Todas las antenas' if i is None else f'{antennas.loc[i,"latitude"]:.6f}, {antennas.loc[i,"longitude"]:.6f} · {antennas.loc[i,"eventos"]} eventos')
support = clean if selection is None else clean[(clean.latitude==antennas.loc[selection,'latitude']) & (clean.longitude==antennas.loc[selection,'longitude'])]
with st.expander('Tabla de soporte',expanded=selection is not None):
    st.dataframe(support,use_container_width=True)
buf = BytesIO()
with pd.ExcelWriter(buf,engine='openpyxl') as writer:
    antennas.drop(columns='radius').to_excel(writer,index=False,sheet_name='ANTENAS_FILTRADAS')
    support.to_excel(writer,index=False,sheet_name='EVENTOS_SELECCIONADOS')
st.download_button('Exportar antenas filtradas y eventos seleccionados',buf.getvalue(),'mapa_soporte.xlsx')
