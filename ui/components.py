"""Reusable visual components for Go Mapper Streamlit pages.

Presentation-only helpers. They do not mutate datasets, filters, exports, or KMZ logic.
"""
from __future__ import annotations

from contextlib import contextmanager
from html import escape
from typing import Iterable, Mapping

import streamlit as st


def _badge_html(text: str, tone: str = "neutral") -> str:
    return f'<span class="gm-badge gm-badge-{escape(tone)}">{escape(str(text))}</span>'


def render_status_badge(label: str, tone: str = "neutral") -> None:
    st.markdown(_badge_html(label, tone), unsafe_allow_html=True)


def render_app_header(title: str, subtitle: str, badges: Iterable[str] | None = None) -> None:
    badge_html = "".join(_badge_html(b, "light") for b in (badges or []))
    st.markdown(
        f"""
<div class="gm-app-hero">
  <div class="gm-hero-grid"></div>
  <div class="gm-eyebrow">CENTRO DE MANDO CDR</div>
  <h1>{escape(title)}</h1>
  <p>{escape(subtitle)}</p>
  <div class="gm-badge-row">{badge_html}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_page_header(
    title: str,
    subtitle: str = "",
    status: str = "Operativo",
    tags: Iterable[str] | None = None,
) -> None:
    tag_html = "".join(_badge_html(t, "neutral") for t in (tags or []))
    st.markdown(
        f"""
<div class="gm-page-head">
  <div>
    <div class="gm-page-kicker">{escape(status)}</div>
    <h1>{escape(title)}</h1>
    {f'<p>{escape(subtitle)}</p>' if subtitle else ''}
  </div>
  <div class="gm-page-tags">{tag_html}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_section(title: str, subtitle: str = "", icon: str = "") -> None:
    icon_html = f'<span class="gm-section-index">{escape(icon)}</span>' if icon else ""
    st.markdown(
        f"""
<div class="gm-section-title">{icon_html}<div><h3>{escape(title)}</h3>{f'<p>{escape(subtitle)}</p>' if subtitle else ''}</div></div>
""",
        unsafe_allow_html=True,
    )


def render_step_header(step: str, title: str, subtitle: str = "") -> None:
    st.markdown(
        f"""
<div class="gm-step-head">
  <span>{escape(step)}</span>
  <div><strong>{escape(title)}</strong>{f'<p>{escape(subtitle)}</p>' if subtitle else ''}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_kpi_card(label: str, value: object, help_text: str = "", tone: str = "neutral") -> None:
    st.markdown(
        f"""
<div class="gm-kpi-card gm-kpi-{escape(tone)}">
  <div class="gm-kpi-label">{escape(label)}</div>
  <div class="gm-kpi-value">{escape(str(value))}</div>
  {f'<div class="gm-kpi-help">{escape(help_text)}</div>' if help_text else ''}
</div>
""",
        unsafe_allow_html=True,
    )


def render_kpi_row(items: Iterable[Mapping[str, object]], columns: int | None = None) -> None:
    data = list(items)
    if not data:
        return
    cols = st.columns(columns or len(data))
    for index, item in enumerate(data):
        with cols[index % len(cols)]:
            render_kpi_card(
                str(item.get("label", "")),
                item.get("value", ""),
                str(item.get("help", item.get("help_text", ""))),
                str(item.get("tone", "neutral")),
            )


def render_module_card(title: str, description: str, tag: str = "Módulo", status: str = "Activo") -> None:
    st.markdown(
        f"""
<div class="gm-module-card">
  <div class="gm-module-top"><span>{escape(tag)}</span><em>{escape(status)}</em></div>
  <div class="gm-module-title">{escape(title)}</div>
  <div class="gm-module-desc">{escape(description)}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_info_panel(title: str, body: str, tone: str = "neutral") -> None:
    st.markdown(
        f"""
<div class="gm-info-panel gm-info-{escape(tone)}">
  <strong>{escape(title)}</strong>
  <p>{escape(body)}</p>
</div>
""",
        unsafe_allow_html=True,
    )


@contextmanager
def render_card():
    """Use Streamlit's bordered container when available for clean control grouping."""
    with st.container(border=True):
        yield
