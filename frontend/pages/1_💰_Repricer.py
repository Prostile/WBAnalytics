import os
import sys
import time

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, ColumnsAutoSizeMode, GridOptionsBuilder, GridUpdateMode

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.api_client import APIClient

st.set_page_config(page_title="Price Lock", page_icon="🔒", layout="wide")
st.title("🔒 Price Lock")
st.caption("Автоматический контур только возвращает цену WB к зафиксированной продавцовой цене. Экономические рекомендации не применяются автоматически.")

col_refresh, col_run, col_apply, col_spacer = st.columns([1, 1, 1, 2])
with col_refresh:
    if st.button("🔄 Обновить", use_container_width=True):
        st.rerun()
with col_run:
    if st.button("▶️ Проверить сейчас", type="primary", use_container_width=True):
        with st.spinner("Проверяю фиксированные цены..."):
            result = APIClient.run_auto_now()
            if result:
                st.success(f"Проверено {result.get('checked_items', 0)}, исправлено {result.get('changed_items', 0)}.")
                time.sleep(1.1)
                st.rerun()

items_data = APIClient.get_repricer_status()
automation_status = APIClient.get_automation_status()
history_payload = APIClient.get_repricer_history(limit=25)
history_data = history_payload.get("events", [])

if not items_data:
    st.info("Нет данных для отображения.")
    st.stop()

df = pd.DataFrame(items_data)
last_run = automation_status.get("last_run") or {}
last_run_at = last_run.get("finished_at") or last_run.get("started_at") or "Еще не запускался"
if last_run_at != "Еще не запускался":
    try:
        last_run_at = pd.to_datetime(last_run_at).strftime("%d.%m.%Y %H:%M")
    except Exception:
        pass

m1, m2, m3, m4 = st.columns(4)
m1.metric("Последняя проверка", last_run_at)
m2.metric("С Price Lock", automation_status.get("locked_items", automation_status.get("auto_mode_items", 0)))
m3.metric("Отклонение цены", automation_status.get("pending_auto_items", 0))
m4.metric("Рекомендации", automation_status.get("manual_review_items", 0))
st.info(automation_status.get("strategy_description", "Price Lock удерживает зафиксированную цену WB."))

if last_run.get("status") == "failed":
    st.error(f"Последний цикл завершился ошибкой: {last_run.get('error_message', 'неизвестно')}")

tab_all, tab_drift, tab_review, tab_setup = st.tabs(["Все товары", "Отклонение цены", "Ручной разбор", "Не готовы"])


def render_grid(dataframe: pd.DataFrame, key_suffix: str):
    if dataframe.empty:
        st.success("В этой категории нет товаров.")
        return None

    display_columns = [
        "nm_id",
        "name",
        "price_lock_enabled",
        "status",
        "reason_label",
        "current_price",
        "locked_final_price",
        "price_drift",
        "price_tolerance_rub",
        "wb_discount",
        "locked_discount",
        "target_base_price",
        "current_profit",
        "min_profit_rub",
        "recommended_price_final",
        "min_viable_price",
        "recommendation_reason_text",
    ]
    display_df = dataframe[[col for col in display_columns if col in dataframe.columns]].copy()

    gb = GridOptionsBuilder.from_dataframe(display_df)
    gb.configure_default_column(resizable=True, filterable=True, sortable=True)
    gb.configure_selection(selection_mode="multiple", use_checkbox=True)
    gb.configure_grid_options(enableRangeSelection=True)
    gb.configure_column("nm_id", header_name="Артикул", width=110, pinned="left")
    gb.configure_column("name", header_name="Товар", width=260, pinned="left")
    gb.configure_column("price_lock_enabled", header_name="Lock", width=90)
    gb.configure_column("status", header_name="Статус", width=120)
    gb.configure_column("reason_label", header_name="Причина", width=220)
    money_cols = ["current_price", "locked_final_price", "price_drift", "price_tolerance_rub", "target_base_price", "current_profit", "min_profit_rub", "recommended_price_final", "min_viable_price"]
    for col in money_cols:
        if col in display_df.columns:
            gb.configure_column(col, type=["numericColumn"], valueFormatter="x == null ? '' : x.toLocaleString() + ' ₽'")
    for col in ["wb_discount", "locked_discount"]:
        if col in display_df.columns:
            gb.configure_column(col, type=["numericColumn"], valueFormatter="x == null ? '' : x.toLocaleString() + ' %'")

    grid_response = AgGrid(
        display_df,
        gridOptions=gb.build(),
        columns_auto_size_mode=ColumnsAutoSizeMode.FIT_CONTENTS,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        theme="balham",
        height=520,
        allow_unsafe_jscode=True,
        key=f"grid_{key_suffix}",
    )
    return grid_response.get("selected_rows", [])


def render_apply_selected(selected_rows):
    if selected_rows:
        if st.button(f"🔒 Вернуть фиксированную цену ({len(selected_rows)} шт)", type="primary", use_container_width=True):
            updates = []
            for row in selected_rows:
                if row.get("target_base_price") and row.get("locked_discount") is not None:
                    updates.append({"nm_id": int(row["nm_id"]), "new_price": int(row["target_base_price"]), "new_discount": int(row["locked_discount"])})
            if updates:
                with st.spinner("Отправка задачи в WB..."):
                    if APIClient.batch_update_prices(updates, source="manual_price_lock"):
                        st.success("Задача отправлена в WB.")
                        time.sleep(1)
                        st.rerun()
    else:
        st.button("🔒 Вернуть фиксированную цену (0)", disabled=True, use_container_width=True)

with tab_all:
    selected = render_grid(df, "all")
    render_apply_selected(selected)
with tab_drift:
    selected = render_grid(df[df["should_auto_update"] == True], "drift")
    render_apply_selected(selected)
with tab_review:
    selected = render_grid(df[df["needs_manual_action"] == True], "review")
    render_apply_selected(selected)
with tab_setup:
    setup_df = df[(df["auto_ready"] == False) | (df["price_lock_enabled"] == False)]
    selected = render_grid(setup_df, "setup")
    render_apply_selected(selected)

st.divider()
st.subheader("История корректировок")
if history_data:
    history_df = pd.DataFrame(history_data)
    history_df["created_at"] = pd.to_datetime(history_df["created_at"], errors="coerce").dt.strftime("%d.%m.%Y %H:%M")
    history_df = history_df.rename(
        columns={
            "created_at": "Когда",
            "item_name": "Товар",
            "source": "Источник",
            "old_price_final": "Цена была",
            "new_price_final": "Цена стала",
            "old_discount": "Скидка была",
            "new_discount": "Скидка стала",
            "reason_label": "Причина",
        }
    )
    st.dataframe(history_df[["Когда", "Товар", "Источник", "Цена была", "Цена стала", "Скидка была", "Скидка стала", "Причина"]], use_container_width=True, hide_index=True)
else:
    st.info("История корректировок пока пуста.")
