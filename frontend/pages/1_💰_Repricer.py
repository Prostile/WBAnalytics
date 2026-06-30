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

col_refresh, col_run, col_apply, col_spacer = st.columns([1, 1, 1, 2])

with col_refresh:
    if st.button("🔄 Обновить данные", use_container_width=True):
        st.rerun()

with col_run:
    if st.button("▶️ Запустить авто-цикл", use_container_width=True):
        with st.spinner("Запускаю фоновую оптимизацию..."):
            result = APIClient.run_auto_now()
            if result:
                st.success(
                    f"Цикл завершен. Проверено {result.get('checked_items', 0)} товаров, изменено {result.get('changed_items', 0)}."
                )
                time.sleep(1.2)
                st.rerun()

# --- 1. ЗАГРУЗКА И ПОДГОТОВКА ДАННЫХ ---
items_data = APIClient.get_repricer_status()
automation_status = APIClient.get_automation_status()
history_payload = APIClient.get_repricer_history(limit=25)
history_data = history_payload.get("events", [])

if not items_data:
    st.info("Нет данных для отображения.")
    st.stop()

df = pd.DataFrame(items_data)
selected = []

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

last_run = automation_status.get("last_run") or {}
last_run_at = last_run.get("finished_at") or last_run.get("started_at") or "Еще не запускался"
if last_run_at != "Еще не запускался":
    try:
        last_run_at = pd.to_datetime(last_run_at).strftime("%d.%m.%Y %H:%M")
    except Exception:
        pass

m1, m2, m3, m4 = st.columns(4)
m1.metric("Последний запуск", last_run_at)
m2.metric("Ждут авто-коррекции", automation_status.get("pending_auto_items", 0))
m3.metric("В ручном разборе", automation_status.get("manual_review_items", 0))
m4.metric("Изменено в цикле", last_run.get("changed_items", 0))

strategy_label = automation_status.get("strategy_label", "Protect Margin")
strategy_description = automation_status.get(
    "strategy_description",
    "Фоновый режим повышает цену только у товаров с прибылью ниже цели и не снижает цену у сверхприбыльных SKU.",
)
st.info(f"Стратегия авто-режима: `{strategy_label}`. {strategy_description}")

if last_run.get("status") == "failed":
    st.error(f"Последний фоновый цикл завершился ошибкой: {last_run.get('error_message', 'неизвестно')}")

# --- 2. ПРЕСЕТЫ (ВИДЫ ОТОБРАЖЕНИЯ) ---
tab_all, tab_bad, tab_auto, tab_setup = st.tabs([
    "📋 Все товары",
    "🔴 Требуют внимания",
    "🤖 На автопилоте",
    "⚪ Не готовы к авто",
])

def render_grid(dataframe, key_suffix):
    """Функция для отрисовки AgGrid с нужными настройками"""
    if dataframe.empty:
        st.success("В этой категории нет товаров.")
        return None

    gb = GridOptionsBuilder.from_dataframe(dataframe)
    gb.configure_default_column(resizable=True, filterable=True, sortable=True)

    # Скрываем лишнее
    for col in ["photo_url", "current_price_retail"]:
        gb.configure_column(col, hide=True)

    # Настраиваем колонки с ПОДСКАЗКАМИ (headerTooltip)
    gb.configure_column("nm_id", header_name="Артикул", width=100, pinned='left')
    gb.configure_column("name", header_name="Товар", width=250, pinned='left', headerTooltip="Название из карточки WB")
    gb.configure_column("mode", header_name="Режим", width=95)
    gb.configure_column("target_profit", header_name="Цель", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'")
    gb.configure_column("wb_discount", header_name="Скидка WB %", type=["numericColumn"], headerTooltip="Текущая скидка продавца, которую вернул WB")
    gb.configure_column("target_discount", header_name="Целевая скидка %", type=["numericColumn"], headerTooltip="Скидка продавца, которую репрайсер будет отправлять вместе с ценой")
    gb.configure_column("current_price", header_name="Сейчас (Клиент)", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", headerTooltip="Текущая цена для покупателя на сайте")
    gb.configure_column("current_profit", header_name="Прибыль (Факт)", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", headerTooltip="Чистая прибыль с одной штуки при текущей цене")
    
    # Рекомендации
    gb.configure_column("recommended_price_final", header_name="Новая (Клиент)", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", headerTooltip="Цена для клиента, которая даст целевую прибыль")
    gb.configure_column("recommended_discount", header_name="Отправим скидку %", type=["numericColumn"], headerTooltip="Скидка продавца, которую отправим по API")
    gb.configure_column("price_delta", header_name="Изменение", width=120, headerTooltip="На сколько процентов изменится базовая цена")
    gb.configure_column("recommended_price_retail", header_name="🚀 Отправим на WB", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'", cellStyle={'backgroundColor': '#e8f4f8', 'fontWeight': 'bold'}, headerTooltip="Базовая цена до скидки. Именно её мы пошлем по API.")
    gb.configure_column("projected_profit", header_name="Прибыль после", type=["numericColumn"], valueFormatter="x.toLocaleString() + ' ₽'")
    gb.configure_column("reason_label", header_name="Комментарий", width=180)
    gb.configure_column("status", header_name="Статус", width=120)
    
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
    if grid_auto and grid_auto['selected_rows'] is not None and len(grid_auto['selected_rows']) > 0:
        selected = grid_auto['selected_rows']

with tab_setup:
    grid_setup = render_grid(df[df['auto_ready'] != True], "setup")
    if grid_setup and grid_setup['selected_rows'] is not None and len(grid_setup['selected_rows']) > 0:
        selected = grid_setup['selected_rows']

# --- 3. ПРИМЕНЕНИЕ ИЗМЕНЕНИЙ ---
with col_apply:
    if selected is not None and len(selected) > 0:
        if isinstance(selected, pd.DataFrame):
            selected_list = selected.to_dict('records')
        else:
            selected_list = selected
            
        if st.button(f"✅ Применить ({len(selected_list)} шт)", type="primary", use_container_width=True):
            to_update = [
                {
                    "nm_id": int(r['nm_id']),
                    "new_price": int(r['recommended_price_retail']),
                    "new_discount": int(r.get('recommended_discount', r.get('target_discount', r.get('wb_discount', 0))) or 0),
                }
                for r in selected_list
                if r.get('recommended_price_retail', 0) > 0
            ]
            if to_update:
                with st.spinner("Отправка на WB..."):
                    if APIClient.batch_update_prices(to_update):
                        st.success("Цены обновлены!")
                        time.sleep(1)
                        st.rerun()
    else:
        st.button("✅ Применить (0 шт)", disabled=True, use_container_width=True)

st.divider()
st.subheader("🕘 История последних корректировок")
if history_data:
    history_df = pd.DataFrame(history_data)
    history_df["created_at"] = pd.to_datetime(history_df["created_at"], errors="coerce").dt.strftime("%d.%m.%Y %H:%M")
    history_df["old_price_retail"] = history_df["old_price_retail"].round(0)
    history_df["new_price_retail"] = history_df["new_price_retail"].round(0)
    history_df["old_profit"] = history_df["old_profit"].round(0)
    history_df["new_profit"] = history_df["new_profit"].round(0)
    history_df = history_df.rename(
        columns={
            "created_at": "Когда",
            "item_name": "Товар",
            "source": "Источник",
            "old_price_retail": "Было",
            "new_price_retail": "Стало",
            "price_delta": "Δ цены",
            "price_delta_percent": "Δ %",
            "old_profit": "Прибыль до",
            "new_profit": "Прибыль после",
            "reason_label": "Причина",
        }
    )
    st.dataframe(
        history_df[["Когда", "Товар", "Источник", "Было", "Стало", "Δ цены", "Δ %", "Прибыль до", "Прибыль после", "Причина"]],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("История автокоррекций пока пуста.")
