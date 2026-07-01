import os
import sys
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from st_aggrid import AgGrid, ColumnsAutoSizeMode, GridOptionsBuilder, GridUpdateMode

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.api_client import APIClient

st.set_page_config(page_title="Финансовая аналитика", page_icon="📊", layout="wide")

st.markdown(
    """
<style>
    .block-container {padding-top: 1.4rem; padding-bottom: 1.5rem; max-width: 1500px;}
    [data-testid="stSidebar"] {background: #f7f8fa; border-right: 1px solid #e5e7eb;}
    h1, h2, h3 {letter-spacing: -0.035em;}
    .app-topline {display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid #e5e7eb; padding-bottom:16px; margin-bottom:18px;}
    .app-title {font-size:28px; font-weight:760; color:#0f172a; letter-spacing:-0.045em; margin:0;}
    .app-subtitle {font-size:13px; color:#64748b; margin-top:3px;}
    .fintech-kpi {border-top:1px solid #e5e7eb; border-bottom:1px solid #e5e7eb; padding:15px 0 13px 0; min-height:90px;}
    .kpi-label {font-size:11px; text-transform:uppercase; letter-spacing:.09em; color:#64748b; font-weight:700;}
    .kpi-value {font-size:26px; color:#111827; font-weight:760; letter-spacing:-.04em; margin-top:7px;}
    .kpi-note {font-size:12px; color:#64748b; margin-top:4px;}
    .section-title {font-size:14px; text-transform:uppercase; letter-spacing:.1em; color:#475569; font-weight:800; margin:26px 0 8px;}
    .chart-shell {border:1px solid #e5e7eb; border-radius:8px; padding:14px; background:#fff;}
    .muted {color:#64748b; font-size:13px;}
    .stButton>button {border-radius:6px; border:1px solid #cbd5e1; box-shadow:none;}
    .stButton>button[kind="primary"] {background:#111827; border-color:#111827;}
</style>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Фильтры")
    period_label = st.radio("Период", ["7 дней", "14 дней", "30 дней", "90 дней", "365 дней"], index=2)
    days = int(period_label.split()[0])
    st.divider()
    st.markdown("### Данные")
    if st.button("Синхронизировать финансовый отчет", type="primary", use_container_width=True):
        with st.spinner("Загружаю отчет WB..."):
            result = APIClient.sync_finance(days=days)
            if result.get("status") == "success":
                st.success(f"Новых строк: {result.get('new_records', 0)}")
                time.sleep(1)
                st.rerun()
            else:
                st.warning(result.get("message", "Данные не обновлены"))
    if st.button("Обновить экран", use_container_width=True):
        st.rerun()

st.markdown(
    """
<div class="app-topline">
  <div>
    <div class="app-title">Финансовая аналитика WB</div>
    <div class="app-subtitle">Фиксированная цена контролируется отдельно; рекомендации по цене показаны в таблице unit-экономики.</div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

summary = APIClient.get_analytics_summary(days=days)
unit_rows = APIClient.get_unit_economics(days=days)
timeseries_rows = APIClient.get_timeseries(days=days)
pnl_rows = APIClient.get_pnl(days=days)

if not summary and not unit_rows:
    st.info("Нет финансовых данных. Откройте фильтры слева и синхронизируйте финансовый отчет.")
    st.stop()


def money(value):
    return f"{float(value or 0):,.0f} ₽".replace(",", " ")


def pct(value):
    return f"{float(value or 0):.1f}%"

k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    st.markdown(f"<div class='fintech-kpi'><div class='kpi-label'>Выручка</div><div class='kpi-value'>{money(summary.get('gross_revenue'))}</div><div class='kpi-note'>до удержаний WB</div></div>", unsafe_allow_html=True)
with k2:
    st.markdown(f"<div class='fintech-kpi'><div class='kpi-label'>К выплате</div><div class='kpi-value'>{money(summary.get('for_pay'))}</div><div class='kpi-note'>по отчету WB</div></div>", unsafe_allow_html=True)
with k3:
    st.markdown(f"<div class='fintech-kpi'><div class='kpi-label'>Прибыль</div><div class='kpi-value'>{money(summary.get('net_profit'))}</div><div class='kpi-note'>{pct(summary.get('margin_pct'))} маржа</div></div>", unsafe_allow_html=True)
with k4:
    st.markdown(f"<div class='fintech-kpi'><div class='kpi-label'>Прибыль / шт</div><div class='kpi-value'>{money(summary.get('avg_profit_per_unit'))}</div><div class='kpi-note'>по продажам</div></div>", unsafe_allow_html=True)
with k5:
    st.markdown(f"<div class='fintech-kpi'><div class='kpi-label'>Возвраты</div><div class='kpi-value'>{pct(summary.get('return_rate_pct'))}</div><div class='kpi-note'>{int(summary.get('returns_qty') or 0)} шт.</div></div>", unsafe_allow_html=True)

st.markdown("<div class='section-title'>Динамика и структура экономики</div>", unsafe_allow_html=True)
chart_col, pnl_col = st.columns([1.45, 1])

with chart_col:
    trend_df = pd.DataFrame(timeseries_rows)
    if not trend_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=trend_df["date"], y=trend_df["revenue"], name="Выручка", mode="lines", line=dict(width=2)))
        fig.add_trace(go.Scatter(x=trend_df["date"], y=trend_df["profit"], name="Прибыль", mode="lines", line=dict(width=2)))
        fig.update_layout(height=330, margin=dict(l=8, r=8, t=22, b=8), legend=dict(orientation="h", y=1.12), template="plotly_white")
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
            )
        )
        fig.update_layout(height=330, margin=dict(l=8, r=8, t=22, b=8), template="plotly_white", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Нет данных для P&L.")

st.markdown("<div class='section-title'>Unit-экономика товаров</div>", unsafe_allow_html=True)
st.markdown("<div class='muted'>Рекомендованная цена — аналитическая подсказка. Автоматически программа меняет только отклонение от зафиксированной цены.</div>", unsafe_allow_html=True)

unit_df = pd.DataFrame(unit_rows)
if unit_df.empty:
    st.info("За выбранный период нет строк unit-экономики.")
    st.stop()

rename_map = {
    "nm_id": "Артикул WB",
    "item_name": "Товар",
    "current_price": "Текущая цена",
    "locked_price": "Фикс. цена",
    "recommended_price": "Рекоменд. цена",
    "min_viable_price": "Мин. жизнесп. цена",
    "sales_qty": "Продажи",
    "returns_qty": "Возвраты",
    "return_rate_pct": "% возвратов",
    "retail_amount": "Выручка",
    "for_pay": "К выплате",
    "logistics": "Логистика",
    "cogs": "Себестоимость",
    "profit": "Прибыль",
    "profit_per_unit": "Прибыль / шт",
    "status": "Статус",
    "recommendation": "Комментарий",
}
visible_columns = [col for col in rename_map.keys() if col in unit_df.columns]
grid_df = unit_df[visible_columns].rename(columns=rename_map)

# Округление для спокойного табличного вида
for col in ["Текущая цена", "Фикс. цена", "Рекоменд. цена", "Мин. жизнесп. цена", "Выручка", "К выплате", "Логистика", "Себестоимость", "Прибыль", "Прибыль / шт"]:
    if col in grid_df.columns:
        grid_df[col] = grid_df[col].astype(float).round(0)
if "% возвратов" in grid_df.columns:
    grid_df["% возвратов"] = grid_df["% возвратов"].astype(float).round(1)

builder = GridOptionsBuilder.from_dataframe(grid_df)
builder.configure_default_column(resizable=True, filterable=True, sortable=True, editable=False)
builder.configure_selection(selection_mode="single", use_checkbox=False)
builder.configure_grid_options(enableRangeSelection=True, rowHeight=38, headerHeight=42)
builder.configure_column("Артикул WB", pinned="left", width=115)
builder.configure_column("Товар", pinned="left", width=260)
for money_col in ["Текущая цена", "Фикс. цена", "Рекоменд. цена", "Мин. жизнесп. цена", "Выручка", "К выплате", "Логистика", "Себестоимость", "Прибыль", "Прибыль / шт"]:
    if money_col in grid_df.columns:
        builder.configure_column(money_col, type=["numericColumn"], valueFormatter="x == null ? '' : x.toLocaleString() + ' ₽'")
if "% возвратов" in grid_df.columns:
    builder.configure_column("% возвратов", type=["numericColumn"], valueFormatter="x == null ? '' : x.toFixed(1) + ' %'")
builder.configure_column("Комментарий", width=360)

grid_response = AgGrid(
    grid_df,
    gridOptions=builder.build(),
    columns_auto_size_mode=ColumnsAutoSizeMode.FIT_CONTENTS,
    update_mode=GridUpdateMode.SELECTION_CHANGED,
    theme="balham",
    height=560,
    allow_unsafe_jscode=True,
)

selected = grid_response.get("selected_rows", [])
if selected:
    row = selected[0]
    with st.expander(f"Детали товара: {row.get('Товар')}", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Фикс. цена", money(row.get("Фикс. цена")))
        c2.metric("Рекоменд. цена", money(row.get("Рекоменд. цена")))
        c3.metric("Прибыль / шт", money(row.get("Прибыль / шт")))
        c4.metric("Возвраты", f"{row.get('% возвратов', 0)}%")
        st.caption(row.get("Комментарий", ""))
