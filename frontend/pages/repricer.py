import os
import sys
import time
from typing import Any

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.api_client import APIClient
from utils.ui_theme import apply_fintech_theme, integer, money, render_header, render_metric_strip, section, selected_rows_to_records

st.set_page_config(page_title="Price Lock", page_icon="🔒", layout="wide")
apply_fintech_theme()

with st.sidebar:
    st.markdown("### Price Lock")
    if st.button("Обновить", use_container_width=True, key="repricer_refresh_sidebar"):
        st.rerun()
    if st.button("Проверить сейчас", type="primary", use_container_width=True, key="repricer_run_sidebar"):
        with st.spinner("Проверяю фиксированные цены..."):
            result = APIClient.run_auto_now()
            if result:
                st.success(f"Проверено: {result.get('checked_items', 0)} · исправлено: {result.get('changed_items', 0)}")
                time.sleep(1.1)
                st.rerun()

render_header(
    title="Price Lock",
    subtitle="Автоматический контур возвращает только продавцовую цену WB к зафиксированному значению. Экономические рекомендации не применяются без ручного решения.",
    overline="WB price control",
)

items_data = APIClient.get_repricer_status()
automation_status = APIClient.get_automation_status()
history_payload = APIClient.get_repricer_history(limit=25)
history_data = history_payload.get("events", [])

if not items_data:
    st.info("Нет данных для отображения. Импортируйте товары в настройках.")
    st.stop()

df = pd.DataFrame(items_data)
last_run = automation_status.get("last_run") or {}
last_run_at = last_run.get("finished_at") or last_run.get("started_at") or "Ещё не запускался"
if last_run_at != "Ещё не запускался":
    try:
        last_run_at = pd.to_datetime(last_run_at).strftime("%d.%m.%Y %H:%M")
    except Exception:
        pass

render_metric_strip(
    [
        {"label": "Последняя проверка", "value": last_run_at, "note": last_run.get("status", "нет статуса")},
        {"label": "С Price Lock", "value": integer(automation_status.get("locked_items", automation_status.get("auto_mode_items", 0))), "note": "готовы к контролю"},
        {"label": "Отклонения", "value": integer(automation_status.get("pending_auto_items", 0)), "note": "требуют возврата цены"},
        {"label": "Рекомендации", "value": integer(automation_status.get("manual_review_items", 0)), "note": "не применяются автоматически"},
        {"label": "Товаров", "value": integer(len(df)), "note": "в текущей базе"},
    ]
)

if last_run.get("status") == "failed":
    st.markdown(f"<div class='note danger-note'>Последний цикл завершился ошибкой: {last_run.get('error_message', 'неизвестно')}</div>", unsafe_allow_html=True)
else:
    st.markdown(
        f"<div class='note'>{automation_status.get('strategy_description', 'Price Lock удерживает зафиксированную цену WB.')}</div>",
        unsafe_allow_html=True,
    )

status_style = JsCode(
    """
    function(params) {
        const value = String(params.value || '').toLowerCase();
        if (value.includes('error') || value.includes('fail') || value.includes('critical')) {
            return {'color': '#b91c1c', 'fontWeight': 800};
        }
        if (value.includes('manual') || value.includes('review') || value.includes('info')) {
            return {'color': '#b45309', 'fontWeight': 800};
        }
        return {'color': '#047857', 'fontWeight': 800};
    }
    """
)
drift_style = JsCode(
    """
    function(params) {
        if (params.value == null) return {};
        if (Math.abs(Number(params.value)) > 0) return {'color': '#b91c1c', 'fontWeight': 800};
        return {'color': '#047857', 'fontWeight': 800};
    }
    """
)


def prepare_table(dataframe: pd.DataFrame) -> pd.DataFrame:
    columns = {
        "nm_id": "nmID",
        "name": "Товар",
        "price_lock_enabled": "Lock",
        "current_price": "Текущая цена",
        "locked_final_price": "Фикс. цена",
        "price_drift": "Отклонение",
        "current_profit": "Прибыль",
        "recommended_price_final": "Рекоменд. цена",
        "min_viable_price": "Мин. цена",
        "status": "Статус",
        "recommendation_reason_text": "Комментарий",
    }
    visible = [col for col in columns if col in dataframe.columns]
    table = dataframe[visible].rename(columns=columns).copy()
    for col in ["Текущая цена", "Фикс. цена", "Отклонение", "Прибыль", "Рекоменд. цена", "Мин. цена"]:
        if col in table.columns:
            table[col] = pd.to_numeric(table[col], errors="coerce").round(0)
    return table


def render_grid(dataframe: pd.DataFrame, key_suffix: str) -> list[dict[str, Any]]:
    if dataframe.empty:
        st.success("В этой категории нет товаров.")
        return []

    table = prepare_table(dataframe)
    builder = GridOptionsBuilder.from_dataframe(table)
    builder.configure_default_column(
        resizable=True,
        filterable=True,
        sortable=True,
        editable=False,
        wrapHeaderText=False,
        autoHeaderHeight=False,
        suppressSizeToFit=True,
    )
    builder.configure_selection(selection_mode="multiple", use_checkbox=True)
    builder.configure_grid_options(rowHeight=44, headerHeight=48, enableCellTextSelection=True, ensureDomOrder=True, suppressHorizontalScroll=False, tooltipShowDelay=150)
    builder.configure_column("nmID", pinned="left", width=120, minWidth=110)
    builder.configure_column("Товар", pinned="left", width=330, minWidth=280, tooltipField="Товар")
    builder.configure_column("Lock", width=86, minWidth=80)
    for col in ["Текущая цена", "Фикс. цена", "Рекоменд. цена", "Мин. цена", "Прибыль"]:
        if col in table.columns:
            builder.configure_column(col, width=142, type=["numericColumn"], valueFormatter="x == null ? '' : x.toLocaleString('ru-RU') + ' ₽'")
    if "Отклонение" in table.columns:
        builder.configure_column("Отклонение", width=130, type=["numericColumn"], valueFormatter="x == null ? '' : x.toLocaleString('ru-RU') + ' ₽'", cellStyle=drift_style)
    if "Статус" in table.columns:
        builder.configure_column("Статус", width=130, cellStyle=status_style)
    if "Комментарий" in table.columns:
        builder.configure_column("Комментарий", width=520, minWidth=360, tooltipField="Комментарий")

    grid_response = AgGrid(
        table,
        gridOptions=builder.build(),
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        theme="balham",
        height=540,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=False,
        key=f"repricer_grid_{key_suffix}_v2",
    )
    return selected_rows_to_records(grid_response.get("selected_rows"))


def render_apply_selected(selected_rows: list[dict[str, Any]], source_df: pd.DataFrame, key_suffix: str) -> None:
    button_key = f"repricer_apply_fixed_{key_suffix}_v2"
    disabled_key = f"repricer_apply_disabled_{key_suffix}_v2"
    if selected_rows:
        if st.button(f"Вернуть фиксированную цену ({len(selected_rows)} шт.)", type="primary", use_container_width=True, key=button_key):
            selected_ids = {int(row.get("nmID")) for row in selected_rows if row.get("nmID") is not None}
            updates = []
            for _, row in source_df[source_df["nm_id"].isin(selected_ids)].iterrows():
                if pd.notna(row.get("target_base_price")) and pd.notna(row.get("locked_discount")):
                    updates.append(
                        {
                            "nm_id": int(row["nm_id"]),
                            "new_price": int(float(row["target_base_price"])),
                            "new_discount": int(float(row["locked_discount"])),
                        }
                    )
            if updates:
                with st.spinner("Отправка задачи в WB..."):
                    if APIClient.batch_update_prices(updates, source="manual_price_lock"):
                        st.success("Задача отправлена в WB.")
                        time.sleep(1)
                        st.rerun()
            else:
                st.warning("У выбранных товаров нет target_base_price или locked_discount.")
    else:
        st.button("Вернуть фиксированную цену (0)", disabled=True, use_container_width=True, key=disabled_key)

section("Контроль фиксированной цены", "Выберите товары с отклонением и вручную отправьте возврат к locked_final_price. Фоновый режим делает то же автоматически по расписанию.")
tab_all, tab_drift, tab_review, tab_setup = st.tabs(["Все товары", "Отклонения", "Ручной разбор", "Не готовы"])

with tab_all:
    selected = render_grid(df, "all")
    render_apply_selected(selected, df, "all")
with tab_drift:
    drift_df = df[df.get("should_auto_update", False) == True] if "should_auto_update" in df.columns else df.iloc[0:0]
    selected = render_grid(drift_df, "drift")
    render_apply_selected(selected, drift_df, "drift")
with tab_review:
    review_df = df[df.get("needs_manual_action", False) == True] if "needs_manual_action" in df.columns else df.iloc[0:0]
    selected = render_grid(review_df, "review")
    render_apply_selected(selected, review_df, "review")
with tab_setup:
    if "auto_ready" in df.columns:
        setup_df = df[(df["auto_ready"] == False) | (df.get("price_lock_enabled", False) == False)]
    else:
        setup_df = df[df.get("price_lock_enabled", False) == False] if "price_lock_enabled" in df.columns else df.iloc[0:0]
    selected = render_grid(setup_df, "setup")
    render_apply_selected(selected, setup_df, "setup")

section("История корректировок")
if history_data:
    history_df = pd.DataFrame(history_data)
    if "created_at" in history_df.columns:
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
    columns = [col for col in ["Когда", "Товар", "Источник", "Цена была", "Цена стала", "Скидка была", "Скидка стала", "Причина"] if col in history_df.columns]
    st.dataframe(history_df[columns], use_container_width=True, hide_index=True, height=260)
else:
    st.info("История корректировок пока пуста.")
