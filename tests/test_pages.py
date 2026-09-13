"""Navigation smoke test using real Streamlit 1.35 AppTest."""
from pathlib import Path
import pandas as pd
from streamlit.testing.v1 import AppTest
from ui.catalog import MODULES

ROOT=Path(__file__).resolve().parents[1]


def app(monkeypatch):
    monkeypatch.chdir(ROOT)
    at=AppTest.from_file(str(ROOT/'app.py'),default_timeout=40)
    at.session_state['logged_in']=True
    at.session_state['suite_auth']=True
    at.run()
    return at


def test_all_catalog_pages_start(monkeypatch):
    at=app(monkeypatch)
    assert not at.exception
    for _,file,_,_,_ in MODULES:
        at.switch_page('pages/'+file).run()
        assert not at.exception, (file,[e.message for e in at.exception])


def test_graph_draws_and_filters_loaded_state(monkeypatch):
    at=app(monkeypatch)
    nodes=pd.DataFrame({'id':['001','002','003'],'label':['Línea A','Línea B','Contacto C'],'tipo':['Línea']*3,'titular':['']*3,'usuario':['']*3})
    edges=pd.DataFrame({'source':['001','002'],'target':['003','003'],'peso_eventos':[4,2],'tipo':['VOZ','SMS']})
    at.session_state['gm_graph']=(nodes,edges,None)
    at.switch_page('pages/app_grafo_inteligente.py').run()
    assert not at.exception
    at.selectbox(key='gm_graph_focus').set_value('001').run()
    assert not at.exception
    assert any('gm-kpi-value">2<' in item.value for item in at.markdown)


def test_login_guard_returns_true_for_authenticated_session(monkeypatch):
    at=app(monkeypatch)
    at.switch_page('pages/app_linea_tiempo.py').run()
    assert not at.exception
    assert len(at.get('file_uploader'))==1


def test_logout_removes_case_data(monkeypatch):
    at=app(monkeypatch)
    at.session_state['confidential_case_fixture']='synthetic'
    at.button(key='logout_sidebar').click().run()
    assert not at.exception
    assert 'confidential_case_fixture' not in at.session_state
    assert not at.session_state['logged_in']
