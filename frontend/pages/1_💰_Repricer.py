import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, ColumnsAutoSizeMode
import time
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.api_client import APIClient

st.set_page_config(page_title="Умный Репрайсер", page_icon="💰", layout="wide")

st.title("💰 Умный Репрайсер")

col_refresh, col_apply, col_spacer = st.columns([1, 1, 3])

with col_refresh:
    if st.button("🔄 Обновить данные", use_container_width=True):
        st.rerun()

# --- 1. ЗАГРУЗКА И ПОДГОТОВКА ДАННЫХ ---
items_data = APIClient.get_repricer_status()

if not items_data:
    st.info("Нет данных для отображения.")
    st.stop()

df = pd.DataFrame(items_data)

# Считаем визуальную дельту (процент изменения цены)
def calculate_delta(row):
    old = row.get('current_price_retail', 0)
    new = row.get('recommended_price_retail', 0)
    if not old or old == 0 or not new or new == 0:
        return "⚪ 0%"
    pct = ((new - old) / old) * 100
    if pct > 0: return f"🟢 +{pct:.1f}%"
    elif pct < 0: return f"🔴 {pct:.1f}%"
    return "⚪ 0%"

df['price_delta'] = df.apply(calculate_delta, axis=1)

# --- 2. ПРЕСЕТЫ (ВИДЫ ОТОБРАЖЕНИЯ) ---
tab_all, tab_bad, tab_auto = st.tabs(["📋 Все товары", "🔴 Требуют внимания", "🤖 На автопилоте"])

def render_grid(dataframe, key_suffix):
    """Функция для отрисовки AgGrid с нужными настройками"""
    if dataframe.empty:
        st.success("В этой категории нет товаров.")
        return None

    gb = GridOptionsBuilder.from_dataframe(dataframe)
    gb.configure_default_column(resizable=True, filterable=True, sortable=True)

    # Скрываем лишнее
    for col in ["photo_url", "mode", "current_price_retail", "target_profit"]:
        gb.configure_column(col, hide=True)

    # Настраиваем колонки с ПОДСКАЗКАМИ (headerTooltip)
    gb.configure_column("nm_id", header_name="Артикул", width=100, pinned='left')
    gb.configure_column("name", header_name="Товар", width=250, pinned='left', headerTooltip="Название из карточки WB")
    
    gb.configure_column("wb_discount", header_name="Скидка продавца %", type=["numericColumn"], headerTooltip="Ваша скидка в личном кабинете WB")
    gb.configure_column("current_price", header_name="Сейчас (Клиент)", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", headerTooltip="Текущая цена для покупателя на сайте")
    gb.configure_column("current_profit", header_name="Прибыль (Факт)", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", headerTooltip="Чистая прибыль с одной штуки при текущей цене")
    
    # Рекомендации
    gb.configure_column("recommended_price_final", header_name="Новая (Клиент)", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", headerTooltip="Цена для клиента, которая даст целевую прибыль")
    gb.configure_column("price_delta", header_name="Изменение", width=120, headerTooltip="На сколько процентов изменится базовая цена")
    gb.configure_column("recommended_price_retail", header_name="🚀 Отправим на WB", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", cellStyle={'backgroundColor': '#e8f4f8', 'fontWeight': 'bold'}, headerTooltip="Базовая цена до скидки. Именно её мы пошлем по API.")
    
    gb.configure_column("status", header_name="Статус")
    
    gb.configure_selection(selection_mode="multiple", use_checkbox=True)
    grid_options = gb.build()

    return AgGrid(
        dataframe,
        gridOptions=grid_options,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        columns_auto_size_mode=ColumnsAutoSizeMode.FIT_CONTENTS,
        theme="streamlit",
        key=f"grid_{key_suffix}"
    )

with tab_all:
    grid_all = render_grid(df, "all")
    selected = grid_all['selected_rows'] if grid_all else None

with tab_bad:
    grid_bad = render_grid(df[df['status'] != 'OK'], "bad")
    # Если мы на этой вкладке, логично использовать её выделение
    if grid_bad and grid_bad['selected_rows'] is not None and len(grid_bad['selected_rows']) > 0:
        selected = grid_bad['selected_rows']

with tab_auto:
    grid_auto = render_grid(df[df['mode'] == 'auto'], "auto")

# --- 3. ПРИМЕНЕНИЕ ИЗМЕНЕНИЙ ---
with col_apply:
    if selected is not None and len(selected) > 0:
        if isinstance(selected, pd.DataFrame):
            selected_list = selected.to_dict('records')
        else:
            selected_list = selected
            
        if st.button(f"✅ Применить ({len(selected_list)} шт)", type="primary", use_container_width=True):
            to_update = [{"nm_id": int(r['nm_id']), "new_price": int(r['recommended_price_retail'])} for r in selected_list if r.get('recommended_price_retail', 0) > 0]
            if to_update:
                with st.spinner("Отправка на WB..."):
                    if APIClient.batch_update_prices(to_update):
                        st.success("Цены обновлены!")
                        time.sleep(1)
                        st.rerun()
    else:
        st.button("✅ Применить (0 шт)", disabled=True, use_container_width=True)