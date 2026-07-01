import os
import sys
import time
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.api_client import APIClient
from utils.ui_theme import (
    apply_fintech_theme,
    integer,
    money,
    pct,
    render_header,
    render_metric_strip,
    section,
    selected_rows_to_records,
)

st.set_page_config(page_title="Финансовая аналитика", page_icon="📊", layout="wide")
apply_fintech_theme()

PERIOD_OPTIONS = {
    "7 дней": 7,
    "14 дней": 14,
    "30 дней": 30,
    "90 дней": 90,
    "365 дней": 365,
    "За всё время": 0,
}

if "analytics_period_label" not in st.session_state:
    st.session_state.analytics_period_label = "90 дней"

render_header(
    title="Финансовая аналитика WB",
    subtitle="Price Lock удерживает продавцовую цену. Экономика и рекомендованная цена остаются аналитикой и не применяются автоматически.",
    overline="Wildberries · Finance",
)

# Верхняя функциональная панель вместо перегруженного левого sidebar.
bar_left, bar_right = st.columns([1, 0.42], gap="large")
with bar_left:
    st.markdown(
        "<div class='toolbar-title'>Период, синхронизация и обновление вынесены в панель фильтров. Таблица ниже показывает только поля для управленческого решения.</div>",
        unsafe_allow_html=True,
    )
with bar_right:
    with st.popover("Фильтры и данные", use_container_width=True):
        period_label = st.radio(
            "Период анализа",
            list(PERIOD_OPTIONS.keys()),
            index=list(PERIOD_OPTIONS.keys()).index(st.session_state.analytics_period_label),
            key="analytics_period_radio",
        )
        st.session_state.analytics_period_label = period_label
        selected_days = PERIOD_OPTIONS[period_label]
        sync_days = selected_days if selected_days > 0 else 3650
        st.markdown("<div class='compact-help'>Фильтр «За всё время» не ограничивает финансовые строки по дате. Для синхронизации используется максимально широкий период.</div>", unsafe_allow_html=True)
        if st.button("Синхронизировать финансовый отчёт", type="primary", use_container_width=True, key="analytics_sync_report_popover"):
            with st.spinner("Загружаю финансовый отчёт WB..."):
                result = APIClient.sync_finance(days=sync_days)
                if result.get("status") == "success":
                    st.success(f"Новых строк: {result.get('new_records', 0)}")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning(result.get("message", "Данные не обновлены"))
        if st.button("Обновить экран", use_container_width=True, key="analytics_refresh_screen_popover"):
            st.rerun()

days = PERIOD_OPTIONS[st.session_state.analytics_period_label]

summary = APIClient.get_analytics_summary(days=days)
unit_rows = APIClient.get_unit_economics(days=days)
timeseries_rows = APIClient.get_timeseries(days=days)
pnl_rows = APIClient.get_pnl(days=days)

if not summary and not unit_rows:
    st.info("Нет финансовых данных. Откройте «Фильтры и данные» и синхронизируйте финансовый отчёт.")
    st.stop()

sold_qty = summary.get("sales_qty") or 0
render_metric_strip(
    [
        {"label": "Выручка", "value": money(summary.get("gross_revenue")), "note": "до удержаний WB"},
        {"label": "К выплате", "value": money(summary.get("for_pay")), "note": "по отчёту WB"},
        {"label": "Прибыль", "value": money(summary.get("net_profit")), "note": f"маржа {pct(summary.get('margin_pct'))}"},
        {"label": "Прибыль / шт", "value": money(summary.get("avg_profit_per_unit")), "note": f"{integer(sold_qty)} шт. продано"},
        {"label": "Возвраты", "value": pct(summary.get("return_rate_pct")), "note": f"{integer(summary.get('returns_qty'))} шт."},
    ]
)

section("Динамика и структура экономики")
chart_col, pnl_col = st.columns([1.35, 1], gap="large")

with chart_col:
    trend_df = pd.DataFrame(timeseries_rows)
    if not trend_df.empty:
        trend_df["date"] = pd.to_datetime(trend_df["date"], errors="coerce")
        trend_df = trend_df.sort_values("date")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=trend_df["date"], y=trend_df["revenue"], name="Выручка", mode="lines", line=dict(width=2.2, color="#2563eb")))
        fig.add_trace(go.Scatter(x=trend_df["date"], y=trend_df["profit"], name="Прибыль", mode="lines", line=dict(width=2.2, color="#0f172a")))
        fig.update_layout(
            height=330,
            margin=dict(l=4, r=4, t=24, b=4),
            legend=dict(orientation="h", y=1.12, x=0),
            template="plotly_white",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="#ffffff",
            font=dict(size=12, color="#334155"),
        )
        fig.update_xaxes(showgrid=False, tickfont=dict(color="#64748b"))
        fig.update_yaxes(gridcolor="#e5eaf1", tickfont=dict(color="#64748b"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Нет точек для графика динамики.")

with pnl_col:
    pnl_df = pd.DataFrame(pnl_rows)
    if not pnl_df.empty:
        measures = ["relative"] * max(len(pnl_df) - 1, 0) + ["total"]
        fig = go.Figure(
            go.Waterfall(
                x=pnl_df["name"],
                y=pnl_df["value"],
                measure=measures,
                text=[money(v) for v in pnl_df["value"]],
                textposition="outside",
                connector={"line": {"color": "#cbd5e1"}},
                increasing={"marker": {"color": "#059669"}},
                decreasing={"marker": {"color": "#ef4444"}},
                totals={"marker": {"color": "#2563eb"}},
            )
        )
        fig.update_layout(
            height=330,
            margin=dict(l=4, r=4, t=24, b=4),
            template="plotly_white",
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="#ffffff",
            font=dict(size=12, color="#334155"),
        )
        fig.update_xaxes(tickangle=-35, tickfont=dict(color="#64748b"))
        fig.update_yaxes(gridcolor="#e5eaf1", tickfont=dict(color="#64748b"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Нет данных для P&L.")

section(
    "Unit-экономика товаров",
    "Показаны только ключевые поля. Для чтения всей строки используйте горизонтальную прокрутку и подсказки при наведении.",
)

unit_df = pd.DataFrame(unit_rows)
if unit_df.empty:
    st.info("За выбранный период нет строк unit-экономики.")
    st.stop()

rename_map = {
    "nm_id": "nmID",
    "item_name": "Товар",
    "sales_qty": "Продано",
    "return_rate_pct": "Возвраты",
    "current_price": "Текущая цена",
    "locked_price": "Фикс. цена",
    "recommended_price": "Рекоменд. цена",
    "min_viable_price": "Мин. цена",
    "profit_per_unit": "Прибыль / шт",
    "profit": "Прибыль",
    "status": "Статус",
    "recommendation": "Комментарий",
}
visible_columns = [col for col in rename_map if col in unit_df.columns]
grid_df = unit_df[visible_columns].rename(columns=rename_map).copy()

money_cols = ["Текущая цена", "Фикс. цена", "Рекоменд. цена", "Мин. цена", "Прибыль / шт", "Прибыль"]
for col in money_cols:
    if col in grid_df.columns:
        grid_df[col] = pd.to_numeric(grid_df[col], errors="coerce").round(0)
if "Возвраты" in grid_df.columns:
    grid_df["Возвраты"] = pd.to_numeric(grid_df["Возвраты"], errors="coerce").round(1)
if "Продано" in grid_df.columns:
    grid_df["Продано"] = pd.to_numeric(grid_df["Продано"], errors="coerce").round(0)

status_style = JsCode(
    """
    function(params) {
        const value = String(params.value || '').toLowerCase();
        if (value.includes('critical') || value.includes('loss') || value.includes('убыт')) return {'color': '#b91c1c', 'fontWeight': 800};
        if (value.includes('warning') || value.includes('info')) return {'color': '#b45309', 'fontWeight': 800};
        return {'color': '#047857', 'fontWeight': 800};
    }
    """
)
profit_style = JsCode(
    """
    function(params) {
        if (params.value == null) return {};
        if (Number(params.value) < 0) return {'color': '#b91c1c', 'fontWeight': 800};
        return {'color': '#0f172a', 'fontWeight': 750};
    }
    """
)

builder = GridOptionsBuilder.from_dataframe(grid_df)
builder.configure_default_column(
    resizable=True,
    filterable=True,
    sortable=True,
    editable=False,
    wrapHeaderText=False,
    autoHeaderHeight=False,
    suppressSizeToFit=True,
)
builder.configure_selection(selection_mode="single", use_checkbox=False)
builder.configure_grid_options(
    rowHeight=44,
    headerHeight=48,
    suppressHorizontalScroll=False,
    enableCellTextSelection=True,
    ensureDomOrder=True,
    tooltipShowDelay=150,
)
builder.configure_column("nmID", pinned="left", width=120, minWidth=110, maxWidth=140)
builder.configure_column("Товар", pinned="left", width=310, minWidth=280, tooltipField="Товар")
if "Продано" in grid_df.columns:
    builder.configure_column("Продано", width=96, type=["numericColumn"], valueFormatter="x == null ? '' : x.toFixed(0)")
if "Возвраты" in grid_df.columns:
    builder.configure_column("Возвраты", width=112, type=["numericColumn"], valueFormatter="x == null ? '' : x.toFixed(1) + ' %'")
for col in ["Текущая цена", "Фикс. цена", "Рекоменд. цена", "Мин. цена", "Прибыль"]:
    if col in grid_df.columns:
        builder.configure_column(col, width=144, type=["numericColumn"], valueFormatter="x == null ? '' : x.toLocaleString('ru-RU') + ' ₽'")
if "Прибыль / шт" in grid_df.columns:
    builder.configure_column("Прибыль / шт", width=144, type=["numericColumn"], valueFormatter="x == null ? '' : x.toLocaleString('ru-RU') + ' ₽'", cellStyle=profit_style)
if "Статус" in grid_df.columns:
    builder.configure_column("Статус", width=120, cellStyle=status_style)
if "Комментарий" in grid_df.columns:
    builder.configure_column("Комментарий", width=460, minWidth=360, tooltipField="Комментарий")

grid_response = AgGrid(
    grid_df,
    gridOptions=builder.build(),
    update_mode=GridUpdateMode.SELECTION_CHANGED,
    theme="balham",
    height=560,
    allow_unsafe_jscode=True,
    fit_columns_on_grid_load=False,
    key="analytics_unit_grid_v2",
)

selected_records = selected_rows_to_records(grid_response.get("selected_rows"))
if selected_records:
    selected: dict[str, Any] = selected_records[0]
    with st.expander(f"Детали выбранного товара: {selected.get('Товар', 'товар')}", expanded=False):
        detail_cols = st.columns(5)
        details = [
            ("Фиксированная цена", selected.get("Фикс. цена"), money),
            ("Рекомендованная цена", selected.get("Рекоменд. цена"), money),
            ("Минимальная цена", selected.get("Мин. цена"), money),
            ("Прибыль / шт", selected.get("Прибыль / шт"), money),
            ("Возвраты", selected.get("Возвраты"), lambda v: f"{float(v or 0):.1f}%"),
        ]
        for col, (label, value, formatter) in zip(detail_cols, details):
            col.metric(label, formatter(value))
        st.caption(selected.get("Комментарий", "Нет комментария"))
