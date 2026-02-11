import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from st_aggrid import AgGrid, GridOptionsBuilder, ColumnsAutoSizeMode
import pandas as pd

def render_kpi_cards(kpis: dict):
    """Отрисовывает верхний ряд карточек с главными метриками."""
    st.markdown("### 💰 Ключевые показатели")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Грязная Выручка", f"{kpis['gross_revenue']:,.0f} ₽", help="Сколько заплатили клиенты (до удержаний WB)")
    m2.metric("Чистая Прибыль", f"{kpis['net_profit']:,.0f} ₽", help="Ваши реальные деньги (Выплата - Себест - Логистика)")
    m3.metric("Рентабельность", f"{kpis['margin']:.1f}%", help="Доля прибыли в грязной выручке")
    
    # Считаем долю логистики от выручки для контроля (чем меньше, тем лучше)
    logistics_share = (kpis['logistics'] / kpis['gross_revenue'] * 100) if kpis['gross_revenue'] > 0 else 0
    m4.metric("Доля Логистики", f"{logistics_share:.1f}%", delta_color="inverse", help="Какой % от выручки съедают покатушки")

def render_waterfall_chart(kpis: dict):
    """Строит каскадный график P&L."""
    fig = go.Figure(go.Waterfall(
        name="P&L",
        orientation="v",
        measure=["relative", "relative", "relative", "relative", "total"],
        x=["Грязная выручка", "Комиссия WB", "Себестоимость", "Логистика", "Чистая Прибыль"],
        textposition="outside",
        text=[f"{int(x):,}" for x in [
            kpis['gross_revenue'], 
            -kpis['wb_commission'], 
            -kpis['cogs'], 
            -kpis['logistics'], 
            kpis['net_profit']
        ]],
        y=[kpis['gross_revenue'], -kpis['wb_commission'], -kpis['cogs'], -kpis['logistics'], 0],
        connector={"line":{"color":"rgb(63, 63, 63)"}},
        decreasing={"marker":{"color":"#ef553b"}},
        increasing={"marker":{"color":"#00cc96"}},
        totals={"marker":{"color":"#636efa"}}
    ))
    fig.update_layout(height=450, margin=dict(t=30, b=20, l=0, r=0), title="Где деньги? (Водопад P&L)")
    st.plotly_chart(fig, use_container_width=True)

def render_trend_chart(trend_df: pd.DataFrame):
    """Строит график динамики по дням."""
    if trend_df.empty:
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=trend_df['date'], y=trend_df['retail_amount'], fill='tozeroy', name='Выручка', line=dict(color='#82ca9d')))
    fig.add_trace(go.Scatter(x=trend_df['date'], y=trend_df['profit'], fill='tozeroy', name='Прибыль', line=dict(color='#8884d8')))
    fig.update_layout(height=350, margin=dict(l=0, r=0, t=30, b=0), title="Динамика по дням", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)

def render_expense_pie_chart(kpis: dict):
    """Строит круговую диаграмму структуры расходов."""
    labels = ['Комиссия WB', 'Себестоимость', 'Логистика', 'Чистая Прибыль']
    values = [max(0, kpis['wb_commission']), max(0, kpis['cogs']), max(0, kpis['logistics']), max(0, kpis['net_profit'])]
    
    fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.4, textinfo='label+percent')])
    fig.update_layout(height=400, margin=dict(l=0, r=0, t=30, b=0), title="Структура распределения выручки")
    st.plotly_chart(fig, use_container_width=True)

def render_abc_grid(abc_df: pd.DataFrame):
    """Настраивает и отрисовывает продвинутую таблицу Unit-экономики."""
    gb = GridOptionsBuilder.from_dataframe(abc_df)
    gb.configure_grid_options(enableRangeSelection=True)
    
    gb.configure_column("item_name", header_name="Товар", pinned='left', width=200)
    
    # Группа: Штуки и Выкуп
    gb.configure_column("sales_qty", header_name="Продажи (шт)", type=["numericColumn"], width=110)
    gb.configure_column("returns_qty", header_name="Возвраты (шт)", type=["numericColumn"], width=110)
    gb.configure_column("return_rate_pct", header_name="% Возвратов", type=["numericColumn"], valueFormatter="x.toFixed(1) + ' %'", width=110, cellStyle={'color': '#ef553b', 'fontWeight': 'bold'})
    
    # Группа: Финансы
    gb.configure_column("retail_amount", header_name="Грязная Выручка", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", aggFunc='sum', width=130)
    gb.configure_column("wb_commission", header_name="Комиссия WB", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", aggFunc='sum', width=120)
    gb.configure_column("logistics", header_name="Логистика", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", aggFunc='sum', width=110)
    
    # Группа: Прибыль
    gb.configure_column("profit", header_name="Общая Прибыль", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", aggFunc='sum', cellStyle={'backgroundColor': '#e8f4f8', 'fontWeight': 'bold'}, width=130)
    gb.configure_column("profit_per_unit", header_name="Прибыль с 1 шт", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", headerTooltip="Сколько чистыми приносит одна проданная единица", width=130)
    
    # Скрываем лишнее
    for col in ['amount', 'real_cogs', 'net_qty']:
        if col in abc_df.columns:
            gb.configure_column(col, hide=True)

    grid_options = gb.build()

    AgGrid(
        abc_df,
        gridOptions=grid_options,
        columns_auto_size_mode=ColumnsAutoSizeMode.FIT_CONTENTS,
        theme="streamlit",
        height=500,
        allow_unsafe_jscode=True
    )