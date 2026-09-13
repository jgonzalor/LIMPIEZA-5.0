"""Shared navigation using the same catalog as the launcher."""
from pathlib import Path
from html import escape
import sys
import streamlit as st
from ui.catalog import MODULES, VERSION
from ui.styles import inject_global_styles

ROOT = Path(__file__).resolve().parent


def _logout():
    # End the session including confidential analysis data from all modules.
    for key in list(st.session_state):
        del st.session_state[key]
    st.rerun()


def render_suite_sidebar():
    inject_global_styles()
    active = Path(str(getattr(sys.modules.get('__main__'), '__file__', ''))).name
    with st.sidebar:
        st.markdown(f'<div class="gm-sidebar-brand"><div class="gm-sidebar-brand-title">◈ GO MAPPER</div><div class="gm-sidebar-brand-sub">INTELIGENCIA TELEFÓNICA · {VERSION}</div></div>', unsafe_allow_html=True)
        st.page_link('app.py', label='Inicio · Centro de operaciones', icon='🏠')
        for group in dict.fromkeys(m[0] for m in MODULES):
            st.markdown(f'<div class="gm-nav-group">{escape(group)}</div>', unsafe_allow_html=True)
            for _, file, icon, label, _ in [m for m in MODULES if m[0] == group]:
                if (ROOT / 'pages' / file).is_file():
                    st.page_link(f'pages/{file}', label=label, icon=icon)
        st.divider()
        user = st.session_state.get('username') or st.session_state.get('user_name') or 'Sesión activa'
        st.caption(f'Sesión: {user}')
        if st.button('Cerrar sesión', use_container_width=True, key='logout_sidebar'):
            _logout()
