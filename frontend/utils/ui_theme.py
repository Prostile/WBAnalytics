from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def selected_rows_to_records(selected_rows: Any) -> list[dict[str, Any]]:
    """Normalize AgGrid selected_rows across streamlit-aggrid versions.

    Some versions return a list of dicts, others return a DataFrame.
    Do not use `if selected_rows` directly: pandas raises an ambiguous truth-value error.
    """
    if selected_rows is None:
        return []
    if isinstance(selected_rows, pd.DataFrame):
        return selected_rows.to_dict(orient="records") if not selected_rows.empty else []
    if isinstance(selected_rows, list):
        return selected_rows
    try:
        return list(selected_rows)
    except TypeError:
        return []



def apply_fintech_theme() -> None:
    """Apply a compact fintech-style theme to Streamlit pages.

    The project remains Streamlit-based, but the visual layer should follow the
    HTML reference: sterile app shell, dense layout, low border radius, readable
    data grids and functional panels instead of decorative cards.
    """

    st.markdown(
        """
<style>
    :root {
        --app-bg: #f5f7fb;
        --surface: #ffffff;
        --surface-muted: #f8fafc;
        --border: #dfe5ee;
        --border-strong: #cbd5e1;
        --text: #0f172a;
        --muted: #64748b;
        --muted-2: #94a3b8;
        --primary: #111827;
        --accent: #2563eb;
        --success: #047857;
        --warning: #b45309;
        --danger: #b91c1c;
        --row-hover: #f7faff;
    }

    .stApp { background: var(--app-bg); color: var(--text); }
    .block-container {
        max-width: 1680px;
        padding-top: 24px;
        padding-left: 28px;
        padding-right: 28px;
        padding-bottom: 32px;
    }

    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stToolbar"] { opacity: .45; }
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }

    [data-testid="stSidebar"] {
        background: #eef2f7;
        border-right: 1px solid var(--border);
    }
    [data-testid="stSidebar"] section { padding-top: 26px; }
    [data-testid="stSidebarNav"] { padding-top: 14px; }
    [data-testid="stSidebarNav"] ul { gap: 2px; }
    [data-testid="stSidebarNav"] a {
        border-radius: 6px;
        margin: 2px 12px;
        min-height: 34px;
        color: #334155;
        font-weight: 580;
        font-size: 13px;
    }
    [data-testid="stSidebarNav"] a:hover { background: #e2e8f0; color: var(--text); }

    h1, h2, h3, h4 { letter-spacing: -.035em; color: var(--text); }
    h1 { font-size: 34px !important; line-height: 1.08 !important; margin-bottom: 8px !important; }
    h2 { font-size: 24px !important; }
    h3 { font-size: 18px !important; }

    .app-header {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 22px;
        padding-bottom: 18px;
        margin-bottom: 18px;
        border-bottom: 1px solid var(--border);
    }
    .app-overline {
        color: var(--muted);
        text-transform: uppercase;
        font-size: 11px;
        letter-spacing: .12em;
        font-weight: 800;
        margin-bottom: 8px;
    }
    .app-title {
        font-size: 32px;
        line-height: 1.08;
        font-weight: 830;
        letter-spacing: -.052em;
        margin: 0;
    }
    .app-subtitle {
        margin-top: 8px;
        color: var(--muted);
        font-size: 14px;
        max-width: 920px;
    }
    .app-actions { display:flex; gap: 10px; align-items:center; }

    .metric-strip {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 0;
        border-top: 1px solid var(--border);
        border-bottom: 1px solid var(--border);
        background: var(--surface);
        margin: 14px 0 22px;
    }
    .metric-cell {
        padding: 17px 18px 15px;
        min-height: 94px;
        border-right: 1px solid var(--border);
    }
    .metric-cell:last-child { border-right: 0; }
    .metric-label {
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: .095em;
        font-size: 11px;
        font-weight: 800;
        white-space: nowrap;
    }
    .metric-value {
        margin-top: 8px;
        color: var(--text);
        font-size: 28px;
        line-height: 1.05;
        font-weight: 820;
        letter-spacing: -.045em;
        font-variant-numeric: tabular-nums;
    }
    .metric-note { margin-top: 6px; color: var(--muted); font-size: 12px; }

    .section-heading {
        margin: 26px 0 12px;
        padding-top: 4px;
        color: #334155;
        font-size: 12px;
        font-weight: 850;
        letter-spacing: .12em;
        text-transform: uppercase;
    }
    .section-caption { color: var(--muted); font-size: 13px; margin-top: -4px; margin-bottom: 12px; }

    .panel {
        border: 1px solid var(--border);
        background: var(--surface);
        border-radius: 8px;
        padding: 16px;
    }
    .panel-flat {
        border: 1px solid var(--border);
        background: var(--surface);
        border-radius: 8px;
        padding: 0;
        overflow: hidden;
    }
    .side-panel {
        border: 1px solid var(--border);
        background: var(--surface);
        border-radius: 8px;
        padding: 16px;
        min-height: 360px;
        position: sticky;
        top: 16px;
    }
    .side-panel-title { font-size: 15px; font-weight: 820; letter-spacing: -.02em; margin-bottom: 12px; }
    .side-panel-muted { color: var(--muted); font-size: 13px; line-height: 1.5; }
    .kv { padding: 10px 0; border-bottom: 1px solid var(--border); }
    .kv:last-child { border-bottom: 0; }
    .kv-label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; font-weight: 750; }
    .kv-value { margin-top: 4px; font-size: 18px; font-weight: 780; font-variant-numeric: tabular-nums; }
    .mono { font-variant-numeric: tabular-nums; }

    .note {
        border-left: 3px solid var(--accent);
        background: #eff6ff;
        padding: 12px 14px;
        color: #1e3a8a;
        font-size: 13px;
        line-height: 1.5;
        margin: 12px 0;
    }
    .danger-note { border-left-color: var(--danger); background: #fef2f2; color: #7f1d1d; }

    div[data-testid="stMetric"] {
        background: var(--surface);
        border-top: 1px solid var(--border);
        border-bottom: 1px solid var(--border);
        padding: 12px 0;
    }
    [data-testid="stMetricLabel"] { color: var(--muted); font-size: 12px; }
    [data-testid="stMetricValue"] { font-size: 28px; font-weight: 800; letter-spacing: -.04em; }

    .stButton>button, .stDownloadButton>button, [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primary"] {
        border-radius: 6px !important;
        border: 1px solid var(--border-strong) !important;
        box-shadow: none !important;
        min-height: 38px;
        font-weight: 700;
    }
    [data-testid="stBaseButton-primary"] {
        background: var(--primary) !important;
        border-color: var(--primary) !important;
        color: #fff !important;
    }
    .stTabs [data-baseweb="tab-list"] { gap: 18px; border-bottom: 1px solid var(--border); }
    .stTabs [data-baseweb="tab"] { height: 40px; padding: 0; font-weight: 730; color: var(--muted); }
    .stTabs [aria-selected="true"] { color: var(--text) !important; }

    div[data-testid="stDataFrame"] { border-radius: 8px; }

    .ag-theme-balham, .ag-theme-streamlit {
        --ag-font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        --ag-font-size: 13px;
        --ag-header-height: 42px;
        --ag-row-height: 42px;
        --ag-border-color: #dfe5ee;
        --ag-row-border-color: #e5eaf1;
        --ag-header-background-color: #f8fafc;
        --ag-odd-row-background-color: #ffffff;
        --ag-background-color: #ffffff;
        --ag-selected-row-background-color: #eaf2ff;
        --ag-row-hover-color: #f7faff;
        --ag-range-selection-border-color: #2563eb;
    }
    .ag-header-cell-label { font-weight: 800; color: #334155; }
    .ag-cell { display: flex; align-items: center; }


    .toolbar-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        margin: 8px 0 16px;
    }
    .toolbar-title { color: var(--muted); font-size: 13px; }
    .compact-help { color: var(--muted); font-size: 12px; line-height: 1.45; }

    .ag-theme-balham .ag-header-cell,
    .ag-theme-streamlit .ag-header-cell {
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    .ag-theme-balham .ag-header-cell-label,
    .ag-theme-streamlit .ag-header-cell-label {
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    .ag-theme-balham .ag-cell,
    .ag-theme-streamlit .ag-cell {
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    .ag-center-cols-viewport { min-height: unset !important; }

    @media (max-width: 1100px) {
        .block-container { padding-left: 18px; padding-right: 18px; }
        .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .metric-cell { border-bottom: 1px solid var(--border); }
        .app-header { display:block; }
    }
</style>
""",
        unsafe_allow_html=True,
    )


def render_header(title: str, subtitle: str, overline: str | None = None) -> None:
    overline_html = f"<div class='app-overline'>{overline}</div>" if overline else ""
    st.markdown(
        f"""
<div class="app-header">
  <div>
    {overline_html}
    <h1 class="app-title">{title}</h1>
    <div class="app-subtitle">{subtitle}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def money(value: Any) -> str:
    try:
        return f"{float(value or 0):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def pct(value: Any) -> str:
    try:
        return f"{float(value or 0):.1f}%"
    except (TypeError, ValueError):
        return "—"


def integer(value: Any) -> str:
    try:
        return f"{int(float(value or 0)):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def render_metric_strip(metrics: list[dict[str, str]]) -> None:
    cells = []
    for item in metrics:
        cells.append(
            f"""
<div class="metric-cell">
  <div class="metric-label">{item.get('label', '')}</div>
  <div class="metric-value">{item.get('value', '—')}</div>
  <div class="metric-note">{item.get('note', '')}</div>
</div>
"""
        )
    st.markdown(f"<div class='metric-strip'>{''.join(cells)}</div>", unsafe_allow_html=True)


def section(title: str, caption: str | None = None) -> None:
    caption_html = f"<div class='section-caption'>{caption}</div>" if caption else ""
    st.markdown(f"<div class='section-heading'>{title}</div>{caption_html}", unsafe_allow_html=True)
