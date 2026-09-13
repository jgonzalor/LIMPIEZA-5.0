"""Validated graph operations independent of Streamlit; never infer subscriber identity."""
import json
import math
from html import escape
import pandas as pd
import networkx as nx

NODE_COLUMNS = ['id', 'label', 'tipo', 'titular', 'usuario']
EDGE_COLUMNS = ['source', 'target', 'tipo', 'peso_eventos']


def validate_graph(nodes, edges):
    nodes, edges = nodes.copy(), edges.copy()
    for col in ['id']:
        if col not in nodes:
            raise ValueError('NODOS requiere la columna id.')
    for col in ['source', 'target']:
        if col not in edges:
            if not edges.empty:
                raise ValueError('ARISTAS requiere source y target.')
            edges[col] = pd.Series(dtype=str)
    for frame, cols in [(nodes, ['id']), (edges, ['source','target'])]:
        for col in cols:
            if frame[col].isna().any() or frame[col].astype(str).str.strip().eq('').any():
                raise ValueError(f'Hay valores vacíos en {col}.')
            frame[col] = frame[col].astype(str).str.strip()
    if nodes['id'].duplicated().any():
        raise ValueError('Hay identificadores de nodo repetidos. Cada id debe ser único.')
    dangling = (set(edges['source']) | set(edges['target'])) - set(nodes['id'])
    if dangling:
        raise ValueError(f'Hay relaciones con nodos inexistentes: {", ".join(sorted(dangling)[:5])}')
    if 'peso_eventos' not in edges:
        edges['peso_eventos'] = 1
    weights = pd.to_numeric(edges['peso_eventos'], errors='coerce')
    if (weights.isna() | ~weights.map(math.isfinite) | (weights <= 0) | (weights % 1 != 0)).any():
        raise ValueError('peso_eventos debe contener enteros positivos.')
    edges['peso_eventos'] = weights.astype('int64')
    for col in NODE_COLUMNS:
        if col not in nodes:
            nodes[col] = nodes['id'] if col == 'label' else ''
    nodes['label'] = nodes['label'].fillna(nodes['id'])
    return nodes.fillna(''), edges.fillna('')


def from_cdr(frame, source, target, event_type=None, filename='CDR'):
    if source == target:
        raise ValueError('Selecciona columnas distintas para origen y destino.')
    valid = frame[source].notna() & frame[target].notna()
    valid &= frame[source].astype(str).str.strip().ne('') & frame[target].astype(str).str.strip().ne('')
    evidence = frame.loc[valid].copy()
    evidence['archivo_origen'] = filename
    evidence['fila_excel'] = [int(i)+2 for i in evidence.index]
    evidence['source'] = evidence[source].astype(str).str.strip()
    evidence['target'] = evidence[target].astype(str).str.strip()
    evidence['tipo_relacion'] = evidence[event_type].fillna('No especificado').astype(str) if event_type else 'No especificado'
    edges = evidence.groupby(['source','target','tipo_relacion'], sort=False).size().reset_index(name='peso_eventos').rename(columns={'tipo_relacion':'tipo'})
    ids = sorted(set(evidence['source']) | set(evidence['target']))
    nodes = pd.DataFrame({'id':ids, 'label':ids, 'tipo':'Línea', 'titular':'', 'usuario':''})
    nodes, edges = validate_graph(nodes, edges)
    return nodes, edges, evidence, int((~valid).sum())


def network(nodes, edges):
    graph = nx.Graph()
    graph.add_nodes_from(nodes['id'])
    for row in edges.itertuples():
        graph.add_edge(row.source, row.target)
    return graph


def filter_graph(nodes, edges, focus=None, depth=1, minimum=1):
    visible_edges = edges[edges['peso_eventos'] >= minimum].copy()
    graph = network(nodes, visible_edges)
    ids = set(nodes['id'])
    if focus:
        ids = set(nx.single_source_shortest_path_length(graph, focus, cutoff=depth))
    visible_edges = visible_edges[visible_edges['source'].isin(ids) & visible_edges['target'].isin(ids)]
    return nodes[nodes['id'].isin(ids)].copy(), visible_edges


def render_html(nodes, edges, layout='Circular', height=700, focus=None):
    from pyvis.network import Network
    net = Network(height=f'{height}px', width='100%', directed=True, bgcolor='#F6F9FE', font_color='#253B58', cdn_resources='in_line')
    degree = network(nodes, edges).degree
    ordered = nodes.sort_values('id').reset_index(drop=True)
    count = max(len(ordered),1)
    radius = max(230, count*10)
    for i, row in ordered.iterrows():
        tooltip = '<br>'.join(f'{escape(k)}: {escape(str(row.get(k,"")))}' for k in ['id','tipo','titular','usuario'])
        options = {}
        if layout == 'Circular':
            options = {'x':radius*math.cos(2*math.pi*i/count), 'y':radius*math.sin(2*math.pi*i/count), 'physics':False}
        net.add_node(row['id'], label=str(row['label'] or row['id']), title=tooltip,
                     shape='dot', size=min(38, 16+degree[row['id']]*1.5),
                     color='#E39B35' if row['id']==focus else '#326CCB', **options)
    for row in edges.itertuples():
        net.add_edge(row.source,row.target,value=int(row.peso_eventos),
                     title=f'{escape(str(getattr(row,"tipo","")))} · {row.peso_eventos} eventos', color='#A2B6D1')
    net.set_options(json.dumps({'physics':{'enabled':layout!='Circular', 'stabilization':{'iterations':180}},
        'interaction':{'hover':True, 'navigationButtons':True, 'keyboard':True},
        'edges':{'smooth':{'type':'dynamic'}, 'arrows':{'to':{'enabled':True, 'scaleFactor':0.6}}},
        'nodes':{'font':{'size':15},'borderWidth':2}}))
    return net.generate_html().replace('</script>', '</script>')
