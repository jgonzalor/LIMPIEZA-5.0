"""Grafo Inteligente 4.1: diagram first, explicit validation and source evidence."""
from io import BytesIO
import hashlib
import json
import pandas as pd
import networkx as nx
import streamlit as st
st.set_page_config(page_title="Go Mapper Suite", page_icon="🗺️", layout="wide")
import streamlit.components.v1 as components
from guardian import login_guard
from suite_nav import render_suite_sidebar
from ui.components import render_page_header, render_kpi_row
from core.graph_engine import validate_graph, from_cdr, network, filter_graph, render_html


def workbook(nodes, edges, evidence=None):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        nodes.to_excel(writer,index=False,sheet_name='NODOS')
        edges.to_excel(writer,index=False,sheet_name='ARISTAS')
        if evidence is not None:
            evidence.to_excel(writer,index=False,sheet_name='EVIDENCIA_ORIGINAL')
    return buf.getvalue()


def main():
    pass  # Page configuration is initialized before rendering.
    login_guard('Grafo Inteligente')
    render_suite_sidebar()
    render_page_header('Grafo Inteligente', 'Explora relaciones, consulta contactos comunes y documenta titulares o usuarios con información acreditada.', tags=['Circular','Evidencia','Excel / JSON / HTML'])
    if notice := st.session_state.pop("gm_graph_loaded_notice", None):
        st.success(notice)
    with st.expander('Cargar o sustituir el grafo', expanded='gm_graph' not in st.session_state):
        mode = st.radio('Fuente', ['Grafo JSON / Excel', 'CDR limpio'], horizontal=True)
        upload = st.file_uploader('Archivo de trabajo',type=['json','xlsx','csv'],key='gm_graph_upload')
        if upload:
            try:
                evidence = None
                skipped = 0
                if mode == 'Grafo JSON / Excel':
                    if upload.name.lower().endswith('.json'):
                        payload = json.loads(upload.getvalue().decode('utf-8'))
                        nodes = pd.DataFrame(payload.get('nodos', []))
                        edges = pd.DataFrame(payload.get('aristas', []))
                    else:
                        nodes = pd.read_excel(upload,sheet_name='NODOS',dtype=str)
                        edges = pd.read_excel(upload,sheet_name='ARISTAS',dtype=str)
                else:
                    if upload.name.lower().endswith('.csv'):
                        frame = pd.read_csv(upload,dtype=str)
                    else:
                        xls = pd.ExcelFile(upload)
                        sheet = st.selectbox('Hoja de datos',xls.sheet_names,index=xls.sheet_names.index('Datos_Limpios') if 'Datos_Limpios' in xls.sheet_names else 0)
                        frame = pd.read_excel(xls,sheet_name=sheet,dtype=str)
                    columns = list(frame.columns)
                    a,b,c = st.columns(3)
                    source = a.selectbox('Origen →',columns,index=columns.index('Número A') if 'Número A' in columns else 0)
                    target = b.selectbox('→ Destino',columns,index=columns.index('Número B') if 'Número B' in columns else min(1,len(columns)-1))
                    kind = c.selectbox('Tipo de evento',['Sin clasificar']+columns,index=columns.index('Tipo')+1 if 'Tipo' in columns else 0)
                    st.caption('Las flechas siguen las columnas elegidas. Confirma si A/B representan origen/destino en tu archivo. Excluye tráfico DATOS si deseas analizar solo comunicaciones entre líneas.')
                    if kind != 'Sin clasificar':
                        types = sorted(frame[kind].dropna().unique())
                        chosen = st.multiselect('Tipos a incorporar',types,default=[t for t in types if not any(x in t.upper() for x in ['DATOS','GPRS','INTERNET'])])
                        frame = frame[frame[kind].isin(chosen)]
                    nodes, edges, evidence, skipped = from_cdr(frame,source,target,kind if kind!='Sin clasificar' else None,upload.name)
                if st.button('Cargar grafo',type='primary'):
                    nodes, edges = validate_graph(nodes,edges)
                    if nodes.empty:
                        raise ValueError('No se encontraron entidades válidas en la selección.')
                    st.session_state['gm_graph'] = (nodes,edges,evidence)
                    st.session_state['gm_graph_revision'] = st.session_state.get('gm_graph_revision',0)+1
                    st.session_state.pop('gm_graph_focus',None)
                    st.session_state["gm_graph_loaded_notice"] = f"Grafo cargado: {len(nodes)} entidades. Filas sin extremos omitidas: {skipped}."
                    st.rerun()
            except (ValueError,KeyError,TypeError,AttributeError,ImportError) as error:
                st.error(f'No se pudo cargar: {error}')
    if 'gm_graph' not in st.session_state:
        st.info('Carga un grafo con hojas NODOS / ARISTAS o un CDR limpio. La visualización aparecerá aquí.')
        return
    nodes,edges,evidence = st.session_state['gm_graph']
    a,b,c,d = st.columns([3,1,1,1])
    labels = dict(zip(nodes['id'],nodes['label']))
    focus = a.selectbox('Buscar entidad / ver su entorno',[None]+list(nodes['id']),format_func=lambda x:'Todas las entidades' if x is None else f'{labels[x]} · {x}',key='gm_graph_focus')
    depth = b.selectbox('Saltos',[1,2,3])
    minimum = c.number_input('Eventos mínimos',min_value=1,value=1)
    layout = d.selectbox('Diseño',['Circular','Dinámico'])
    visible_nodes,visible_edges = filter_graph(nodes,edges,focus,depth,minimum)
    graph = network(visible_nodes,visible_edges)
    render_kpi_row([{'label':'Entidades visibles','value':len(visible_nodes)},
                    {'label':'Relaciones visibles','value':len(visible_edges)},
                    {'label':'Eventos representados','value':int(visible_edges['peso_eventos'].sum())},
                    {'label':'Componentes','value':nx.number_connected_components(graph)}],columns=4)
    diagram, detail, editor, exports = st.tabs(['Diagrama','Relaciones y soporte','Editar entidades','Exportar'])
    with diagram:
        if len(visible_nodes)>500 or len(visible_edges)>3000:
            st.info('Este grafo es grande. Selecciona una entidad, reduce los saltos o aumenta el mínimo de eventos para renderizar hasta 500 entidades y 3,000 relaciones. El archivo completo sigue disponible en Exportar.')
        else:
            try:
                html = render_html(visible_nodes,visible_edges,layout,focus=focus)
                components.html(html,height=730,scrolling=False)
                st.download_button('Descargar diagrama visible HTML',html,'grafo_visible.html','text/html')
            except Exception as error:
                st.error(f'No se pudo dibujar el grafo: {error}')
        st.caption('El tamaño del nodo representa sus conexiones. Las flechas siguen source → target; titulares y usuarios son datos documentados manualmente, no inferidos.')
    with detail:
        pair = st.multiselect('Comparar contactos comunes (elige dos entidades)',list(nodes['id']),max_selections=2)
        if len(pair)==2:
            full = network(nodes,edges)
            common = sorted(set(full.neighbors(pair[0])) & set(full.neighbors(pair[1])) - set(pair))
            st.write(f'Contactos comunes: {len(common)} (conexión en cualquier sentido, grafo completo).')
            st.dataframe(nodes[nodes['id'].isin(common)],use_container_width=True)
        st.dataframe(visible_edges,use_container_width=True)
        if evidence is not None:
            st.caption('Filas de la carga original. Las ediciones manuales del grafo no modifican esta evidencia.')
            keys = set(zip(visible_edges['source'],visible_edges['target'],visible_edges.get('tipo',pd.Series('',index=visible_edges.index))))
            support = evidence[[ (a,b,t) in keys for a,b,t in zip(evidence['source'],evidence['target'],evidence['tipo_relacion']) ]]
            st.dataframe(support,use_container_width=True)
    with editor:
        st.caption('Los cambios se aplican juntos al guardar. Conserva los id para mantener las relaciones y la correspondencia con el archivo original.')
        revision = st.session_state.get('gm_graph_revision',0)
        with st.form(f'graph_edit_{revision}'):
            new_nodes = st.data_editor(nodes,num_rows='dynamic',use_container_width=True,key=f'graph_nodes_{revision}')
            new_edges = st.data_editor(edges,num_rows='dynamic',use_container_width=True,key=f'graph_edges_{revision}')
            save = st.form_submit_button('Validar y guardar cambios')
        if save:
            try:
                valid_nodes,valid_edges = validate_graph(new_nodes,new_edges)
                st.session_state['gm_graph'] = (valid_nodes,valid_edges,evidence)
                st.session_state['gm_graph_revision'] = revision+1
                # The selectbox was already instantiated: clear it on the next run.
                st.session_state['gm_graph_reset_focus'] = True
                st.rerun()
            except ValueError as error:
                st.error(str(error))
    with exports:
        st.caption('Estos archivos contienen el grafo completo guardado, aunque la vista tenga filtros.')
        st.download_button('Excel completo',workbook(nodes,edges,evidence),'grafo_completo.xlsx')
        payload = {'nodos':nodes.to_dict('records'),'aristas':edges.to_dict('records')}
        st.download_button('JSON editable',json.dumps(payload,ensure_ascii=False,indent=2),'grafo_completo.json','application/json')

if __name__ == '__main__':
    if st.session_state.pop('gm_graph_reset_focus',False):
        st.session_state.pop('gm_graph_focus',None)
    main()
