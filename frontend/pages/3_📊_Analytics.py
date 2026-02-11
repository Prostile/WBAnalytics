import streamlit as st
import pandas as pd
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.api_client import APIClient
import utils.analytics_math as a_math
import utils.analytics_ui as a_ui

st.set_page_config(page_title="Глубокая Аналитика", page_icon="📊", layout="wide")
st.title("📊 Финансовый Дашборд (P&L)")

# --- 1. ПАНЕЛЬ УПРАВЛЕНИЯ И ФИЛЬТРЫ ---
col_filters, col_load = st.columns([3, 1])
with col_filters:
    period_option = st.radio("Период:", ["7 Дней", "14 Дней", "30 Дней", "Все время"], horizontal=True, index=2)
with col_load:
    if st.button("🔄 Скачать свежий отчет V5", type="primary", use_container_width=True):
        with st.spinner("Синхронизация..."):
            APIClient.sync_finance(days=90)
            st.rerun()

# --- 2. ЗАГРУЗКА ДАННЫХ ---
finance_data = APIClient.get_finance_dashboard()
items_list = APIClient.get_items()

if not finance_data.get("records"):
    st.info("Нет данных. Нажмите 'Скачать свежий отчет V5'.")
    st.stop()

# --- 3. ОБРАБОТКА ДАННЫХ (через модуль math) ---
items_map = {i['nm_id']: i for i in items_list}
df = a_math.process_raw_finance_data(finance_data["records"], items_map)

# Фильтрация по дате
from datetime import timedelta
today = pd.Timestamp.now()
if period_option == "7 Дней": start_date = today - timedelta(days=7)
elif period_option == "14 Дней": start_date = today - timedelta(days=14)
elif period_option == "30 Дней": start_date = today - timedelta(days=30)
else: start_date = df['date'].min()

df_filtered = df[df['date'] >= start_date].copy()
if df_filtered.empty:
    st.warning("За этот период нет продаж.")
    st.stop()

# Считаем KPI и подготавливаем срезы
kpis = a_math.calculate_global_kpis(df_filtered)
abc_df = a_math.build_abc_analysis(df_filtered)
trend_df = a_math.get_daily_trend(df_filtered)

# --- 4. ОТОБРАЖЕНИЕ (через модуль UI) ---
# Верхние карточки всегда на виду
a_ui.render_kpi_cards(kpis)
st.divider()

# РАЗДЕЛЕНИЕ НА ВКЛАДКИ
tab_summary, tab_unit, tab_expenses = st.tabs([
    "📈 Главный Дашборд", 
    "🛍️ Unit-экономика (ABC)", 
    "💸 Расходы и Потери"
])

with tab_summary:
    c1, c2 = st.columns([3, 2])
    with c1:
        a_ui.render_waterfall_chart(kpis)
    with c2:
        a_ui.render_trend_chart(trend_df)

with tab_unit:
    st.markdown("### 🏆 Анализ рентабельности товаров")
    st.caption("Оцените процент возвратов и чистую прибыль с каждой проданной единицы товара.")
    a_ui.render_abc_grid(abc_df)

with tab_expenses:
    c1, c2 = st.columns(2)
    with c1:
        a_ui.render_expense_pie_chart(kpis)
    with c2:
        st.markdown("### 🔍 Зоны риска")
        if kpis['gross_revenue'] > 0:
            logistics_pct = kpis['logistics'] / kpis['gross_revenue'] * 100
            returns_total = abc_df['returns_qty'].sum()
            
            st.warning(f"🚛 **Логистика съедает {logistics_pct:.1f}% выручки.** Норма для сумок — до 15%. Если показатель выше, возможно, процент выкупа слишком низкий.")
            st.info(f"🔙 **Всего возвратов за период:** {int(returns_total)} шт. Проверьте вкладку Unit-экономики, чтобы найти самые проблемные артикулы.")