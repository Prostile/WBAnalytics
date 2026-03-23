import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode
import time
import os
import sys

# Подключаем наш API-клиент
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.api_client import APIClient

st.set_page_config(page_title="База Товаров", page_icon="⚙️", layout="wide")

st.title("⚙️ База Данных Товаров")
st.markdown("""
Здесь хранятся финансовые параметры вашей Unit-экономики.  
**Дважды кликните** по ячейке в таблице (например, в колонке *Себестоимость*), чтобы изменить значение. После внесения всех правок нажмите **"Сохранить изменения"**.
""")

# --- 1. ПАНЕЛЬ УПРАВЛЕНИЯ ---
col_import, col_save, col_spacer = st.columns([1, 1, 3])

with col_import:
    if st.button("📥 Импорт из Wildberries", use_container_width=True):
        with st.spinner("Синхронизация карточек с WB..."):
            success = APIClient.import_from_wb()
            if success:
                st.success("Номенклатура успешно обновлена!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Ошибка импорта.")

# --- 2. ЗАГРУЗКА ДАННЫХ ---
items_data = APIClient.get_items()
repricer_status = APIClient.get_repricer_status()
status_map = {item["nm_id"]: item for item in repricer_status}

if not items_data:
    st.info("База пуста. Нажмите 'Импорт из Wildberries', чтобы загрузить ваши товары.")
    st.stop()

df = pd.DataFrame(items_data)
persist_columns = list(df.columns)

df["auto_ready"] = df["nm_id"].map(lambda nm_id: "Да" if status_map.get(nm_id, {}).get("auto_ready") else "Нет")
df["auto_reason"] = df["nm_id"].map(lambda nm_id: status_map.get(nm_id, {}).get("reason_label", "Нет данных"))

active_items = int(df["is_active"].sum()) if "is_active" in df.columns else 0
auto_mode_items = int((df["repricer_mode"] == "auto").sum()) if "repricer_mode" in df.columns else 0
auto_ready_items = int((df["auto_ready"] == "Да").sum())

m1, m2, m3, m4 = st.columns(4)
m1.metric("Товаров", len(df))
m2.metric("Активных", active_items)
m3.metric("В авто-режиме", auto_mode_items)
m4.metric("Готово к авто", auto_ready_items)
st.caption("Для участия в фоновой оптимизации товар должен быть активен, переведен в режим `auto`, иметь себестоимость, цель прибыли и актуальную цену WB.")

# --- 3. НАСТРОЙКА AGGRID ДЛЯ РЕДАКТИРОВАНИЯ ---
gb = GridOptionsBuilder.from_dataframe(df)

# Общие настройки: разрешаем фильтры и изменение размеров колонок
gb.configure_default_column(
    resizable=True,
    filterable=True,
    sortable=True,
    editable=False # По умолчанию запрещаем, разрешим только нужным
)

# Скрываем системные поля
gb.configure_column("photo_url", hide=True)
gb.configure_column("wb_price_base", hide=True)
gb.configure_column("wb_discount", hide=True)
gb.configure_column("wb_price_final", hide=True)
gb.configure_column("updated_at", hide=True)

# Закрепляем неизменяемые поля (ID и Название)
gb.configure_column("nm_id", header_name="Артикул WB", pinned='left', width=120)
gb.configure_column("name", header_name="Название", pinned='left', width=250)
gb.configure_column("vendor_code", header_name="Артикул продавца", width=150)

# РЕДАКТИРУЕМЫЕ КОЛОНКИ (Финансовая модель)
gb.configure_column("cost_price", header_name="Себестоимость (₽)", editable=True, type=["numericColumn"])
gb.configure_column("target_profit", header_name="Цель Прибыли (₽)", editable=True, type=["numericColumn"])
gb.configure_column("wb_commission", header_name="Комиссия WB (0.25 = 25%)", editable=True, type=["numericColumn"])
gb.configure_column("logistics_cost", header_name="Логистика (₽)", editable=True, type=["numericColumn"])
gb.configure_column("tax_rate", header_name="Налог (0.07 = 7%)", editable=True, type=["numericColumn"])
gb.configure_column("min_price", header_name="Мин. порог цены (₽)", editable=True, type=["numericColumn"])
gb.configure_column("is_active", header_name="Активен", editable=True)

# Выпадающий список для режима репрайсера
gb.configure_column(
    "repricer_mode", 
    header_name="Режим", 
    editable=True, 
    cellEditor='agSelectCellEditor', 
    cellEditorParams={'values': ['manual', 'auto']}
)
gb.configure_column("auto_ready", header_name="Готов к авто", editable=False, width=110)
gb.configure_column("auto_reason", header_name="Комментарий", editable=False, width=220)

grid_options = gb.build()

# --- 4. ОТОБРАЖЕНИЕ ТАБЛИЦЫ ---
st.subheader("📋 Редактор параметров")
st.caption("Подсказка: Изменения не вступят в силу, пока вы не нажмете кнопку 'Сохранить'.")

grid_response = AgGrid(
    df,
    gridOptions=grid_options,
    data_return_mode=DataReturnMode.AS_INPUT,
    update_mode=GridUpdateMode.MODEL_CHANGED,
    fit_columns_on_grid_load=False, # Чтобы не сжимало колонки слишком сильно
    theme="streamlit",
    height=600
)

# --- 5. СОХРАНЕНИЕ ИЗМЕНЕНИЙ ---
with col_save:
    if st.button("💾 Сохранить изменения", type="primary", use_container_width=True):
        # Получаем данные из отредактированной таблицы
        updated_df = grid_response['data']
        records = updated_df.to_dict(orient="records")
        records = [{key: item.get(key) for key in persist_columns} for item in records]
        
        # Индикатор прогресса
        progress_bar = st.progress(0)
        total_items = len(records)
        success_count = 0
        
        # Отправляем обновленные данные на бэкенд по одному (или можно переписать API на bulk update позже)
        for i, item in enumerate(records):
            # APIClient.save_item принимает dict (ItemCreate schema)
            if APIClient.save_item(item):
                success_count += 1
            progress_bar.progress((i + 1) / total_items)
            
        if success_count == total_items:
            st.success(f"Все товары ({success_count} шт) успешно обновлены!")
            time.sleep(1.5)
            st.rerun()
        else:
            st.warning(f"Сохранено {success_count} из {total_items}. Проверьте логи.")
