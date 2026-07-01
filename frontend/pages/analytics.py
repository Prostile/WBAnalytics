import os
import sys
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.api_client import APIClient
from utils.ui_theme import apply_fintech_theme, integer, money, pct, render_header, render_metric_strip, section

st.set_page_config(page_title="Финансовая аналитика", page_icon="📊", layout="wide")
apply_fintech_theme()

with st.sidebar:
    st.markdown("### Фильтры")
    period_label = st.radio(
        "Период",
        ["7 дней", "14 дней", "30 дней", "90 дней", "365 дней"],
        index=3,
        key="analytics_period",
    )
    days = int(period_label.split()[0])
    st.divider()
    st.markdown("### Данные")
    if st.button("Синхронизировать отчёт", type="primary", use_container_width=True, key="analytics_sync_report"):
        with st.spinner("Загружаю финансовый отчёт WB..."):
            result = APIClient.sync_finance(days=days)
            if result.get("status") == "success":
                st.success(f"Новых строк: {result.get('new_records', 0)}")
                time.sleep(1)
                st.rerun()
            else:
                st.warning(result.get("message", "Данные не обновлены"))
    if st.button("Обновить экран", use_container_width=True, key="analytics_refresh_screen"):
        st.rerun()

render_header(
    title="Финансовая аналитика WB",
    subtitle="Фиксированная цена контролируется Price Lock. Рекомендованная цена — только аналитическая подсказка внутри таблицы unit-экономики.",
    overline="Wildberries · Finance",
)

summary = APIClient.get_analytics_summary(days=days)
unit_rows = APIClient.get_unit_economics(days=days)
timeseries_rows = APIClient.get_timeseries(days=days)
pnl_rows = APIClient.get_pnl(days=days)

if not summary and not unit_rows:
    st.info("Нет финансовых данных. Синхронизируйте финансовый отчёт в боковой панели.")
    st.stop()

render_metric_strip(
    [
        {"label": "Выручка", "value": money(summary.get("gross_revenue")), "note": "до удержаний WB"},
        {"label": "К выплате", "value": money(summary.get("for_pay")), "note": "по отчёту WB"},
        {"label": "Прибыль", "value": money(summary.get("net_profit")), "note": f"маржа {pct(summary.get('margin_pct'))}"},
        {"label": "Прибыль / шт", "value": money(summary.get("avg_profit_per_unit")), "note": "по проданным единицам"},
        {"label": "Возвраты", "value": pct(summary.get("return_rate_pct")), "note": f"{integer(summary.get('returns_qty'))} шт."},
    ]
)

section("Динамика и структура экономики")
chart_col, pnl_col = st.columns([1.45, 1], gap="large")

with chart_col:
    trend_df = pd.DataFrame(timeseries_rows)
    if not trend_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=trend_df["date"], y=trend_df["revenue"], name="Выручка", mode="lines", line=dict(width=2.3, color="#2563eb")))
        fig.add_trace(go.Scatter(x=trend_df["date"], y=trend_df["profit"], name="Прибыль", mode="lines", line=dict(width=2.3, color="#ef4444")))
        fig.update_layout(
            height=340,
            margin=dict(l=8, r=8, t=26, b=8),
            legend=dict(orientation="h", y=1.13, x=0),
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
        fig = go.Figure(
            go.Waterfall(
                x=pnl_df["name"],
                y=pnl_df["value"],
                measure=["relative"] * (len(pnl_df) - 1) + ["total"],
                text=[money(v) for v in pnl_df["value"]],
                textposition="outside",
                increasing={"marker": {"color": "#059669"}},
                decreasing={"marker": {"color": "#ef4444"}},
                totals={"marker": {"color": "#2563eb"}},
            )
        )
        fig.update_layout(
            height=340,
            margin=dict(l=8, r=8, t=26, b=8),
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
    "Таблица оставлена компактной: только поля, нужные для принятия решения. Полная расшифровка выбранного товара показана в правой панели.",
)

unit_df = pd.DataFrame(unit_rows)
if unit_df.empty:
    st.info("За выбранный период нет строк unit-экономики.")
    st.stop()

# Нормализуем и оставляем только управленческие поля. Не выводим все технические поля WB в одну кашу.
rename_map = {
    "nm_id": "nmID",
    "item_name": "Товар",
    "sales_qty": "Продажи",
    "return_rate_pct": "Возвраты %",
    "current_price": "Текущая",
    "locked_price": "Фикс.",
    "recommended_price": "Реком.",
    "min_viable_price": "Мин. цена",
    "retail_amount": "Выручка",
    "for_pay": "К выплате",
    "logistics": "Логистика",
    "profit_per_unit": "Прибыль / шт",
    "status": "Статус",
    "recommendation": "Комментарий",
}
visible_columns = [col for col in rename_map if col in unit_df.columns]
grid_df = unit_df[visible_columns].rename(columns=rename_map).copy()

for col in ["Текущая", "Фикс.", "Реком.", "Мин. цена", "Выручка", "К выплате", "Логистика", "Прибыль / шт"]:
    if col in grid_df.columns:
        grid_df[col] = pd.to_numeric(grid_df[col], errors="coerce").round(0)
if "Возвраты %" in grid_df.columns:
    grid_df["Возвраты %"] = pd.to_numeric(grid_df["Возвраты %"], errors="coerce").round(1)

status_style = JsCode(
    """
    function(params) {
        const value = String(params.value || '').toLowerCase();
        if (value.includes('critical') || value.includes('loss') || value.includes('убыт')) {
            return {'color': '#b91c1c', 'fontWeight': 800};
        }
        if (value.includes('warning') || value.includes('info')) {
            return {'color': '#b45309', 'fontWeight': 800};
        }
        return {'color': '#047857', 'fontWeight': 800};
    }
    """
)
profit_style = JsCode(
    """
    function(params) {
        if (params.value == null) return {};
        if (Number(params.value) < 0) return {'color': '#b91c1c', 'fontWeight': 800};
        return {'color': '#0f172a', 'fontWeight': 700};
    }
    """
)

builder = GridOptionsBuilder.from_dataframe(grid_df)
builder.configure_default_column(resizable=True, filterable=True, sortable=True, editable=False, wrapHeaderText=True, autoHeaderHeight=True)
builder.configure_selection(selection_mode="single", use_checkbox=False)
builder.configure_grid_options(
    rowHeight=42,
    headerHeight=44,
    suppressColumnVirtualisation=False,
    suppressHorizontalScroll=False,
    enableCellTextSelection=True,
    ensureDomOrder=True,
)
builder.configure_column("nmID", pinned="left", width=104, minWidth=104, maxWidth=120)
builder.configure_column("Товар", pinned="left", width=255, minWidth=220, tooltipField="Товар")
builder.configure_column("Продажи", width=92, type=["numericColumn"])
builder.configure_column("Возвраты %", width=108, type=["numericColumn"], valueFormatter="x == null ? '' : x.toFixed(1) + ' %'")
for col in ["Текущая", "Фикс.", "Реком.", "Мин. цена", "Выручка", "К выплате", "Логистика"]:
    if col in grid_df.columns:
        builder.configure_column(col, width=118, type=["numericColumn"], valueFormatter="x == null ? '' : x.toLocaleString('ru-RU') + ' ₽'")
if "Прибыль / шт" in grid_df.columns:
    builder.configure_column("Прибыль / шт", width=130, type=["numericColumn"], valueFormatter="x == null ? '' : x.toLocaleString('ru-RU') + ' ₽'", cellStyle=profit_style)
if "Статус" in grid_df.columns:
    builder.configure_column("Статус", width=104, cellStyle=status_style)
if "Комментарий" in grid_df.columns:
    builder.configure_column("Комментарий", width=340, tooltipField="Комментарий", flex=1)

main_col, detail_col = st.columns([4.4, 1.25], gap="large")
with main_col:
    grid_response = AgGrid(
        grid_df,
        gridOptions=builder.build(),
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        theme="balham",
        height=560,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=False,
        key="analytics_unit_grid",
    )

selected_rows = grid_response.get("selected_rows", [])
selected = selected_rows[0] if selected_rows else None
with detail_col:
    st.markdown("<div class='side-panel'>", unsafe_allow_html=True)
    if selected:
        st.markdown(f"<div class='side-panel-title'>{selected.get('Товар', 'Товар')}</div>", unsafe_allow_html=True)
        for label, field in [
            ("Фиксированная цена", "Фикс."),
            ("Рекомендованная цена", "Реком."),
            ("Минимальная цена", "Мин. цена"),
            ("Прибыль / шт", "Прибыль / шт"),
            ("Возвраты", "Возвраты %"),
        ]:
            raw_value = selected.get(field)
            value = f"{raw_value}%" if field == "Возвраты %" else money(raw_value)
            st.markdown(f"<div class='kv'><div class='kv-label'>{label}</div><div class='kv-value'>{value}</div></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='note'><b>Комментарий</b><br>{selected.get('Комментарий', 'Нет комментария')}</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='side-panel-title'>Детали товара</div>", unsafe_allow_html=True)
        st.markdown("<div class='side-panel-muted'>Выберите строку в таблице, чтобы посмотреть фиксированную цену, рекомендацию и экономику товара без расширения таблицы десятками колонок.</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
