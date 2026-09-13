"""Global CSS injection and backwards-compatible UI aliases for Go Mapper."""
from __future__ import annotations

from ui.components import (
    render_app_header,
    render_info_panel,
    render_kpi_card,
    render_kpi_row,
    render_module_card,
    render_page_header,
    render_section,
    render_status_badge,
    render_step_header,
)
import streamlit as st


def inject_global_styles() -> None:
    """Inject compact operational styling for the current Streamlit render."""
    st.markdown(
        """
<style>
:root {
  --gm-bg: #F5F8FB;
  --gm-sidebar: #0B1220;
  --gm-sidebar-soft: #111827;
  --gm-surface: #FFFFFF;
  --gm-surface-soft: #F8FAFC;
  --gm-border: #D8E2EF;
  --gm-border-soft: #E6EDF5;
  --gm-text: #0F172A;
  --gm-muted: #64748B;
  --gm-primary: #0F766E;
  --gm-primary-bright: #14B8A6;
  --gm-primary-soft: #CCFBF1;
  --gm-secondary: #2563EB;
  --gm-secondary-soft: #DBEAFE;
  --gm-warning: #B45309;
  --gm-warning-soft: #FEF3C7;
  --gm-danger: #B91C1C;
  --gm-radius: 14px;
  --gm-shadow: 0 10px 26px rgba(15, 23, 42, .075);
}

/* Hide Streamlit's automatic multipage list; Go Mapper renders the only navigation menu. */
/* Selectors cover Streamlit Cloud and local Streamlit DOM variants. */
[data-testid="stSidebarNav"],
[data-testid="stSidebarNavItems"],
[data-testid="stSidebarNavSeparator"],
div[data-testid="stSidebarNav"],
section[data-testid="stSidebar"] nav[aria-label="Main menu"] {display:none!important;}
/* Keep the sidebar itself and the custom Go Mapper navigation visible. */
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {padding-top:.65rem!important;}
#MainMenu, footer {visibility: hidden;}
[data-testid="stHeader"] {background:transparent;}
.stDeployButton, div[data-testid="stStatusWidget"] {display:none!important;}
.stApp {background: var(--gm-bg); color: var(--gm-text);}
.block-container {max-width: 100% !important; padding-left:1.6rem!important;padding-right:1.6rem!important; padding-top: 3rem !important; padding-bottom: 2.2rem !important;}
h1, h2, h3 {letter-spacing: -.025em; color: var(--gm-text);}
h1 {font-weight: 820 !important;} h2, h3 {font-weight: 760 !important;}

[data-testid="stSidebar"] {background: var(--gm-sidebar); border-right: 1px solid rgba(148,163,184,.20);}
[data-testid="stSidebar"] * {color: #F8FAFC !important;}
[data-testid="stSidebar"] section {padding-top: .65rem;}
[data-testid="stSidebar"] hr {border-color: rgba(148,163,184,.18); margin: .75rem 0;}
[data-testid="stSidebar"] .stButton > button {
  width: 100%; min-height: 2.25rem; border-radius: 10px;
  border: 1px solid rgba(148,163,184,.25); background: rgba(17,24,39,.85);
  font-weight: 700;
}
[data-testid="stSidebar"] [data-testid="stPageLink"] a {
  border-radius: 10px; padding: .35rem .55rem; margin: .08rem 0;
}
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {background: rgba(20,184,166,.12);}

.gm-sidebar-brand {padding: .8rem .85rem; border-radius: 16px; background: linear-gradient(135deg, rgba(20,184,166,.16), rgba(37,99,235,.10)); border: 1px solid rgba(148,163,184,.20); margin-bottom: .55rem;}
.gm-sidebar-brand-title {font-size: 1rem; font-weight: 860;}
.gm-sidebar-brand-sub {font-size: .72rem; color: #CBD5E1!important; margin-top: .1rem;}
.gm-sidebar-user {display:flex; align-items:center; justify-content:space-between; gap:.5rem; padding:.55rem .65rem; border-radius:12px; background:rgba(17,24,39,.72); border:1px solid rgba(148,163,184,.16); margin-bottom:.45rem;}
.gm-sidebar-user strong {font-size:.82rem;} .gm-sidebar-user span {font-size:.72rem; color:#CBD5E1!important;}
.gm-nav-group {font-size:.68rem; color:#94A3B8!important; text-transform:uppercase; letter-spacing:.11em; font-weight:850; margin:.72rem 0 .22rem;}
.gm-active-page {border-left: 3px solid var(--gm-primary-bright); background: rgba(20,184,166,.13); padding:.42rem .58rem; border-radius:10px; font-size:.9rem; font-weight:820; margin:.05rem 0 .18rem;}

.gm-app-hero {position:relative; overflow:hidden; padding:1.75rem 1.9rem; border-radius:22px; background: linear-gradient(135deg,#0B1220 0%,#0F2F3A 54%,#0F766E 120%); color:#F8FAFC; box-shadow: var(--gm-shadow); border:1px solid rgba(255,255,255,.12); margin-bottom:.95rem;}
.gm-hero-grid {position:absolute; inset:0; background-image: linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.045) 1px, transparent 1px); background-size: 32px 32px; mask-image: linear-gradient(90deg, black, transparent 78%);}
.gm-app-hero > *:not(.gm-hero-grid) {position:relative; z-index:1;}
.gm-eyebrow {display:inline-flex; padding:.24rem .62rem; border-radius:999px; background:rgba(20,184,166,.15); border:1px solid rgba(153,246,228,.24); color:#CCFBF1; font-size:.72rem; font-weight:850; letter-spacing:.09em;}
.gm-app-hero h1 {font-size: clamp(2rem, 4vw, 3.25rem); color:#fff; margin:.6rem 0 .3rem;}
.gm-app-hero p {max-width:850px; color:#DDEAF7; margin:0; line-height:1.55;}

.gm-page-head {display:flex; align-items:flex-start; justify-content:space-between; gap:1rem; padding:1rem 1.1rem; border-radius:18px; background:rgba(255,255,255,.92); border:1px solid var(--gm-border); box-shadow:0 8px 22px rgba(15,23,42,.055); margin-bottom:.9rem;}
.gm-page-head h1 {font-size:1.65rem; margin:.08rem 0 .2rem;}
.gm-page-head p {margin:0; color:var(--gm-muted); line-height:1.45; max-width:880px;}
.gm-page-kicker {font-size:.68rem; font-weight:850; color:var(--gm-primary); text-transform:uppercase; letter-spacing:.12em;}
.gm-page-tags,.gm-badge-row {display:flex; flex-wrap:wrap; gap:.35rem; justify-content:flex-end;}
.gm-badge {display:inline-flex; align-items:center; padding:.22rem .52rem; border-radius:999px; font-size:.72rem; font-weight:800; border:1px solid var(--gm-border); white-space:nowrap;}
.gm-badge-neutral {background:#F8FAFC; color:#334155;}
.gm-badge-light {background:rgba(255,255,255,.10); color:#ECFEFF; border-color:rgba(255,255,255,.18);}
.gm-badge-success {background:#D1FAE5; color:#065F46; border-color:#A7F3D0;}
.gm-badge-warning {background:var(--gm-warning-soft); color:var(--gm-warning); border-color:#FDE68A;}
.gm-badge-danger {background:#FEE2E2; color:var(--gm-danger); border-color:#FECACA;}

.gm-section-title {display:flex; gap:.62rem; align-items:flex-start; margin:1rem 0 .45rem;}
.gm-section-index {display:inline-grid; place-items:center; min-width:2rem; height:2rem; border-radius:10px; background:var(--gm-primary-soft); color:var(--gm-primary); font-weight:900; font-size:.78rem;}
.gm-section-title h3 {margin:0; font-size:1.08rem;}
.gm-section-title p {margin:.08rem 0 0; color:var(--gm-muted); font-size:.9rem;}
.gm-step-head {display:flex; align-items:flex-start; gap:.58rem; margin:.15rem 0 .7rem;}
.gm-step-head > span {display:inline-grid; place-items:center; width:2.1rem; height:2.1rem; border-radius:11px; background:#E0F2FE; color:#075985; font-size:.78rem; font-weight:900;}
.gm-step-head strong {display:block; font-size:1rem;} .gm-step-head p {margin:.1rem 0 0; color:var(--gm-muted); font-size:.86rem;}

.gm-module-card,.gm-kpi-card,.gm-info-panel {background:rgba(255,255,255,.96); border:1px solid var(--gm-border); border-radius:var(--gm-radius); box-shadow:0 8px 22px rgba(15,23,42,.052);}
.gm-module-card {padding:.9rem; min-height:142px; transition:transform .16s ease, box-shadow .16s ease; margin-bottom:.45rem;}
.gm-module-card:hover {transform:translateY(-1px); box-shadow:var(--gm-shadow);}
.gm-module-top {display:flex; justify-content:space-between; gap:.5rem; align-items:center; margin-bottom:.55rem;}
.gm-module-top span,.gm-module-top em {font-style:normal; font-size:.68rem; font-weight:850; text-transform:uppercase; letter-spacing:.06em;}
.gm-module-top span {color:var(--gm-primary);} .gm-module-top em {color:var(--gm-muted);}
.gm-module-title {font-size:1rem; font-weight:850; margin-bottom:.28rem; color:var(--gm-text);}
.gm-module-desc {font-size:.86rem; color:var(--gm-muted); line-height:1.4;}
.gm-kpi-card {padding:.78rem .9rem; border-left:4px solid var(--gm-primary); min-height:90px;}
.gm-kpi-warning {border-left-color:var(--gm-warning);} .gm-kpi-danger {border-left-color:var(--gm-danger);} .gm-kpi-secondary {border-left-color:var(--gm-secondary);}
.gm-kpi-label {font-size:.68rem; color:var(--gm-muted); text-transform:uppercase; letter-spacing:.08em; font-weight:850;}
.gm-kpi-value {font-size:1.35rem; font-weight:880; margin-top:.18rem; color:var(--gm-text);}
.gm-kpi-help {font-size:.78rem; color:var(--gm-muted); margin-top:.12rem;}
.gm-info-panel {padding:.85rem .95rem; margin:.55rem 0 .8rem;}
.gm-info-panel strong {display:block; margin-bottom:.18rem;} .gm-info-panel p {margin:0; color:var(--gm-muted); line-height:1.45;}
.gm-info-warning {border-color:#FDE68A; background:#FFFBEB;}

.stButton > button,.stDownloadButton > button {border-radius:11px!important; font-weight:780!important; min-height:2.35rem;}
[data-testid="stBaseButton-primary"] {background:linear-gradient(135deg,var(--gm-primary),var(--gm-secondary))!important; border:0!important;}
[data-testid="stDataFrame"] {border-radius:14px; overflow:hidden; border:1px solid var(--gm-border);}
[data-testid="stMetric"] {background:var(--gm-surface); border:1px solid var(--gm-border); border-radius:14px; padding:.75rem .85rem;}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap:.35rem;}
.gm-module-card {border:0!important;border-radius:0!important;box-shadow:none!important;padding:.35rem!important;min-height:125px!important;}
/* Suite 4.1: readable controls, wide workspace and persistent navigation. */
:root {--gm-primary:#1D4ED8;--gm-primary-soft:#DBEAFE;--gm-border:#DCE4EF;--gm-muted:#52647B;}
[data-testid="stSidebar"] {background:#EEF3FA; border-right:1px solid #DCE4EF;}
[data-testid="stSidebar"] * {color:#253B58!important;}
[data-testid="stSidebar"] .stButton > button {background:white;border-color:#CAD6E5;}
[data-testid="stSidebar"] input {background:white!important;color:#15243B!important;}
.gm-sidebar-brand {background:white; border:1px solid #DCE4EF; padding:1rem;}
.gm-sidebar-brand-sub,.gm-sidebar-user span,.gm-nav-group {color:#52647B!important;}
.gm-sidebar-user {background:#E3ECF8;border:0;}
.gm-active-page {border-color:#1D4ED8;background:#DCE8FC;}
.gm-app-hero {background:linear-gradient(115deg,#132741,#183E6D 65%,#176878);padding:1.4rem 1.6rem;}
.gm-app-hero h1 {font-size:2.3rem;}
.gm-badge-row {justify-content:flex-start;margin-top:.8rem;}
.gm-module-card {min-height:150px;box-shadow:none;border-top:3px solid #3E76D5;}
.gm-module-desc {font-size:.92rem;line-height:1.55;}
.gm-module-title {font-size:1.12rem;}
.gm-kpi-card {box-shadow:none;}
[data-testid="stBaseButton-primary"] {background:#1D4ED8!important;color:white!important;}
[data-testid="stBaseButton-primary"] p {color:white!important;}
button:focus-visible,a:focus-visible,input:focus-visible {outline:3px solid #5B92EE!important;outline-offset:2px;}
[data-testid="stTabs"] button[aria-selected="true"] {color:#1D4ED8;border-bottom:3px solid #1D4ED8;}
[data-testid="stFileUploader"] {border-radius:14px;}
[data-testid="stExpander"] {background:#fff;border-radius:12px;}
@media (max-width:760px) {.block-container{padding-left:1rem!important;padding-right:1rem!important;}.gm-page-head{flex-direction:column;}.gm-app-hero h1{font-size:1.85rem;}.gm-module-card{min-height:0;}}
@media (prefers-reduced-motion:reduce) {*{transition:none!important;}}
</style>
""",
        unsafe_allow_html=True,
    )


# Backwards-compatible names from stage 1.
apply_theme = inject_global_styles


def page_header(title: str, subtitle: str = "", eyebrow: str = "Operativo", badges=None, **_: object) -> None:
    render_page_header(title, subtitle, status=eyebrow, tags=badges)


def section_title(title: str, subtitle: str = "", icon: str = "") -> None:
    render_section(title, subtitle, icon)


def module_card(title: str, description: str, tag: str = "Módulo") -> None:
    render_module_card(title, description, tag)


def kpi_row(items, columns: int | None = None) -> None:
    render_kpi_row(items, columns=columns)


def info_panel(title: str, body: str, tone: str = "neutral") -> None:
    render_info_panel(title, body, tone=tone)
