"""Synthetic regression cases: no real case data or external network required."""
import ast
from pathlib import Path
from io import BytesIO
import zipfile
from xml.etree import ElementTree as ET
import pandas as pd
import pytest
from core.datetime_utils import parse_local_datetime
from core.graph_engine import validate_graph,from_cdr,filter_graph,render_html
from core.map_engine import aggregate_antennas
from core.kml_visibility import hidden_kml

ROOT=Path(__file__).resolve().parents[1]


def page_functions(name, marker):
    # Exercise actual processing functions without executing the page's UI.
    source=(ROOT/'pages'/name).read_text().split(marker)[0]
    tree=ast.parse(source)
    nodes=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.FunctionDef,ast.Assign,ast.AnnAssign))]
    ns={'__file__':str(ROOT/'pages'/name),'__name__':'page_under_test'}
    if 'limpieza' in name:
        from openlocationcode import openlocationcode
        ns['olc']=openlocationcode
        from geopy.geocoders import Nominatim
        from geopy.extra.rate_limiter import RateLimiter
        ns.update(Nominatim=Nominatim,RateLimiter=RateLimiter)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),name,'exec'),ns)
    return ns


@pytest.mark.parametrize('value,hour,expected',[
 ('13/09/2026 18:25',None,'2026-09-13 18:25'),
 ('2026-09-03 18:25',None,'2026-09-03 18:25'),
 ('13-09-2026','06:25 PM','2026-09-13 18:25'),
 (pd.Timestamp('2026-09-13'),.5,'2026-09-13 12:00'),
 ('2026-09-13T18:25:00Z',None,'2026-09-13 11:25'),
 ('2026-09-13T18:25:00-07:00',None,'2026-09-13 18:25'),
])
def test_local_times(value,hour,expected):
    assert parse_local_datetime(value,hour)==pd.Timestamp(expected)


def test_graph_rejects_dangling_and_duplicate_entities():
    nodes=pd.DataFrame({'id':['001','002']})
    with pytest.raises(ValueError,match='inexistentes'):
        validate_graph(nodes,pd.DataFrame({'source':['001'],'target':['999']}))
    with pytest.raises(ValueError,match='repetidos'):
        validate_graph(pd.DataFrame({'id':['001','001']}),pd.DataFrame())


def test_graph_source_rows_and_filters():
    frame=pd.DataFrame({'A':['001','001','002',None],'B':['003','003','003','004']},index=[0,2,3,5])
    nodes,edges,evidence,skipped=from_cdr(frame,'A','B',filename='sintetico.xlsx')
    assert skipped==1 and evidence.fila_excel.tolist()==[2,4,5]
    assert set(nodes.id)=={'001','002','003'}
    assert edges.peso_eventos.sum()==3
    n,e=filter_graph(nodes,edges,'001',1,2)
    assert set(n.id)=={'001','003'} and e.peso_eventos.sum()==2
    html=render_html(n,e)
    assert 'vis-network' in html and '001' in html


def test_invalid_graph_weight():
    for value in [0,-1,float('inf'),1.5,'unknown']:
        with pytest.raises(ValueError,match='enteros positivos'):
            validate_graph(pd.DataFrame({'id':['A']}),pd.DataFrame({'source':['A'],'target':['A'],'peso_eventos':[value]}))


def test_map_rejects_invalid_coordinates():
    frame=pd.DataFrame({'lat':[25,25,91,0],'lon':[-108,-108,-108,0]})
    clean,grouped,invalid=aggregate_antennas(frame,'lat','lon')
    assert invalid==2 and len(clean)==2 and grouped.eventos.tolist()==[2]


def test_normal_kmz_visibility_and_coordinates():
    from modules.kmz_builder import build_kmz
    content=build_kmz(pd.DataFrame({'Latitud':[25.7],'Longitud':[-108.9],'Tipo':['VOZ']}))
    with zipfile.ZipFile(BytesIO(content)) as archive:
        root=ET.fromstring(archive.read('doc.kml'))
    ns={'k':'http://www.opengis.net/kml/2.2'}
    assert all(e.text=='0' for e in root.findall('.//k:visibility',ns))
    assert root.find('.//k:coordinates',ns).text.startswith('-108.9,25.7')
    assert root.find('.//k:Document/k:open',ns).text=='1'


def test_offline_cleaning_preserves_datetimes_and_unknown_duplicates(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    ns=page_functions('app_limpieza_excel.py','# ===========================\n# UI\n')
    Path(ns['PLUS_REPO_DIR']).mkdir(parents=True,exist_ok=True)
    def forbid(*args,**kwargs):
        raise AssertionError('Offline attempted an external location lookup')
    for name in ['reverse_address','pluscode_label','best_admin_label','reverse_best_multi']:
        ns[name]=forbid
    monkeypatch.setattr(ns['requests'],'get',forbid)
    frame=pd.DataFrame({'Tipo':['DATOS','DATOS','DATOS','DATOS','VOZ SALIENTE','VOZ SALIENTE'],
        'Número A':[5550000001]*6,'Número B':[5550000002]*6,
        'Datetime':['13/09/2026 10:00:01','13/09/2026 10:00:40','invalida','invalida','13/09/2026 11:00','13/09/2026 11:00'],
        'Duración (seg)':[5,20,30,40,60,60],'Latitud':[25.7]*6,'Longitud':[-108.9]*6})
    file=BytesIO();frame.to_excel(file,index=False);file.seek(0);file.name='sintetico.xlsx'
    output,name=ns['limpiar_excel'](file,remove_duplicates=True,offline=True)
    xls=pd.ExcelFile(BytesIO(output));clean=pd.read_excel(xls,'Datos_Limpios')
    assert len(clean)==5
    assert clean.Datetime.isna().sum()==2
    assert (clean.Tipo=='VOZ SALIENTE').sum()==2
    assert clean.loc[clean.Datetime.eq(pd.Timestamp('2026-09-13 10:00:40')),'Duración (seg)'].iloc[0]==20
    assert clean.PLUS_CODE.notna().all()
    assert 'OFFLINE' in pd.read_excel(xls,'LOG_Limpieza')['Modo ubicaciones'].iloc[0]
    assert set(xls.sheet_names)=={'Datos_Limpios','LOG_Limpieza','Duplicados','ESTADISTICAS'}


def test_timeline_datetime_only_and_empty():
    ns=page_functions('app_linea_tiempo.py','# ===================== UI principal')
    frame=pd.DataFrame({'Datetime':['13/09/2026 10:00','invalida'],'Tipo':['VOZ SALIENTE','DATOS'],'Número A':['001','001'],'Número B':['002','003']})
    events=ns['construir_eventos'](frame)
    assert len(events)==1 and events.Inicio.iloc[0]==pd.Timestamp('2026-09-13 10:00')
    assert ns['construir_eventos'](frame.iloc[1:]).empty
    assert ns['timeline_pdf_bytes'](events,events.Fecha.iloc[0]).startswith(b'%PDF')


def test_actual_normal_kmz_builder_hides_layers():
    ns=page_functions('app_mapper_azimuth.py','# ─────────────────────────────── UI')
    frame=pd.DataFrame({'PLUS_CODE':['75QHP432+22'],'Latitud':[25.7],'Longitud':[-108.9],
        'Tipo':['VOZ SALIENTE'],'Datetime':[pd.Timestamp('2026-09-13 10:00')],
        'Número A':['5550000001'],'Número B':['5550000002'],'Azimuth_deg':[90],'Duración (seg)':[30]})
    frame=ns['build_datetime'](frame)
    frame['Tipo_norm']=frame['Tipo'].map(ns['canon_tipo'])
    content=ns['generar_kmz'](frame,['VOZ SALIENTE'],100,30,'Prueba sintética',True,0,0,
        '',100,1,0,True,False,'files/test.png',b'fixture',1,'#2563EB',50,'#2563EB',1,1)
    with zipfile.ZipFile(BytesIO(content)) as archive:
        root=ET.fromstring(archive.read('doc.kml'))
        assert archive.read('files/test.png')==b'fixture'
    namespace={'k':'http://www.opengis.net/kml/2.2'}
    assert root.findall('.//k:Placemark',namespace)
    assert all(x.text=='0' for x in root.findall('.//k:visibility',namespace))


def test_map_renderer_has_local_engine_and_no_mapbox_token():
    from core.map_engine import render_map_html
    _,antennas,_=aggregate_antennas(pd.DataFrame({'lat':[25.7],'lon':[-108.9]}),'lat','lon')
    html=render_map_html(antennas)
    assert 'L.circleMarker' in html and 'Fondo no disponible' in html
    assert 'mapbox' not in html.lower()
