"""Go Mapper Suite 4.1 — operational launcher."""
from pathlib import Path
import unicodedata
import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")
from guardian import login_guard
from suite_nav import render_suite_sidebar
from ui.styles import inject_global_styles
from ui.components import render_app_header, render_section, render_module_card, render_kpi_row
from ui.catalog import MODULES, VERSION

inject_global_styles()
login_guard('Centro de operaciones')
render_suite_sidebar()
render_app_header('Cada registro, una pieza del análisis.',
                  'Prepara tus CDR, explora relaciones y construye productos geográficos desde un mismo espacio de trabajo.',
                  badges=[f'GO MAPPER {VERSION}', 'CDR · Vínculos · Cartografía'])
root = Path(__file__).resolve().parent
modules = [m for m in MODULES if (root/'pages'/m[1]).is_file()]
render_kpi_row([
    {'label':'Herramientas disponibles','value':len(modules),'help':'Organizadas por etapa de trabajo'},
    {'label':'Preparación','value':'Offline / Online','help':'Tú eliges si consultar direcciones'},
    {'label':'Secuencia de trabajo','value':'Preparar → Analizar → Exportar','help':'Datos originales y resultados separados'},
], columns=3)
render_section('¿Qué necesitas hacer?', 'Busca una herramienta o elige una etapa del análisis.')
a,b = st.columns([2,3])
query = a.text_input('Buscar módulo', placeholder='Ej. grafo, mapa, limpiar…')
group = b.radio('Etapa', ['Todas','Preparación','Análisis','Geográfico','Reportes','Sistema'], horizontal=True)
def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.lower()) if not unicodedata.combining(c))
selected = [m for m in modules if (group=='Todas' or m[0]==group) and normalized(query) in normalized(' '.join(m))]
if not selected:
    st.info('No hay herramientas con ese filtro. Cambia la búsqueda o elige Todas.')
for stage in dict.fromkeys(m[0] for m in selected):
    render_section(stage)
    cols = st.columns(min(3,sum(m[0]==stage for m in selected)))
    for i, (_, file, icon, title, desc) in enumerate(m for m in selected if m[0]==stage):
        with cols[i % len(cols)]:
            with st.container(border=True):
                render_module_card(f'{icon} {title}', desc, stage, 'Disponible')
                st.page_link(f'pages/{file}', label=f'Abrir {title}', use_container_width=True)
with st.expander('Guía rápida · del archivo al producto final'):
    st.markdown('1. **Armoniza** si el archivo viene en otro formato.\n2. **Limpia** y revisa el LOG antes de analizar.\n3. **Explora** cronología, vínculos y antenas.\n4. **Exporta** el producto y verifica sus datos de soporte.')
    st.caption('Las ubicaciones representan antenas o coberturas aproximadas; no prueban la posición exacta del dispositivo.')
