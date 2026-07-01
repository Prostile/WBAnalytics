import os
import sys
import time
from io import BytesIO

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, DataReturnMode, GridOptionsBuilder, GridUpdateMode

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.api_client import APIClient

IMPORTABLE_COLUMNS = [
    "nm_id",
    "vendor_code",
    "name",
    "cost_price",
    "min_profit_rub",
    "desired_profit_rub",
    "target_profit",
    "logistics_cost",
    "return_cost_per_unit",
    "ads_cost_per_unit",
    "overhead_per_unit",
    "wb_commission",
    "tax_rate",
    "price_lock_enabled",
    "locked_final_price",
    "locked_discount",
    "price_tolerance_rub",
    "pricing_strategy",
    "target_discount",
    "min_price",
    "max_price",
    "repricer_mode",
    "is_active",
]
EXPORT_COLUMNS = IMPORTABLE_COLUMNS + ["auto_ready", "auto_reason"]
NUMERIC_COLUMNS = {
    "cost_price",
    "min_profit_rub",
    "desired_profit_rub",
    "target_profit",
    "logistics_cost",
    "return_cost_per_unit",
    "ads_cost_per_unit",
    "overhead_per_unit",
    "wb_commission",
    "tax_rate",
    "locked_final_price",
    "price_tolerance_rub",
    "min_price",
    "max_price",
}
INTEGER_COLUMNS = {"locked_discount", "target_discount"}
BOOLEAN_COLUMNS = {"is_active", "price_lock_enabled"}
TEXT_COLUMNS = {"vendor_code", "name", "pricing_strategy", "repricer_mode"}
MODE_VALUES = {"manual", "auto", "price_lock"}
STRATEGY_VALUES = {"fixed_final_price", "manual_recommendation"}


def to_csv_bytes(dataframe: pd.DataFrame) -> bytes:
    return dataframe.to_csv(index=False).encode("utf-8-sig")


def to_excel_bytes(dataframe: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="items")
    return buffer.getvalue()


def load_uploaded_table(uploaded_file) -> pd.DataFrame:
    file_bytes = uploaded_file.getvalue()
    file_name = uploaded_file.name.lower()
    if file_name.endswith(".csv"):
        for encoding in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                return pd.read_csv(BytesIO(file_bytes), encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("Не удалось прочитать CSV. Сохраните файл в UTF-8 или CP1251.")
    return pd.read_excel(BytesIO(file_bytes))


def normalize_import_value(column: str, value):
    if pd.isna(value):
        return None
    if column in NUMERIC_COLUMNS:
        return float(value)
    if column in INTEGER_COLUMNS:
        return int(float(value))
    if column in BOOLEAN_COLUMNS:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(int(value))
        normalized = str(value).strip().lower()
        true_values = {"true", "1", "yes", "y", "да", "вкл", "on"}
        false_values = {"false", "0", "no", "n", "нет", "выкл", "off"}
        if normalized in true_values:
            return True
        if normalized in false_values:
            return False
        raise ValueError("ожидалось логическое значение")
    if column == "repricer_mode":
        normalized = str(value).strip().lower()
        if normalized not in MODE_VALUES:
            raise ValueError("режим должен быть manual, auto или price_lock")
        return normalized
    if column == "pricing_strategy":
        normalized = str(value).strip().lower()
        if normalized not in STRATEGY_VALUES:
            raise ValueError("стратегия должна быть fixed_final_price или manual_recommendation")
        return normalized
    if column in TEXT_COLUMNS:
        return str(value).strip()
    return value


def values_equal(left, right) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        try:
            return abs(float(left or 0) - float(right or 0)) < 1e-9
        except (TypeError, ValueError):
            return left == right
    return left == right


def display_value(value) -> str:
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if value is None:
        return "—"
    return str(value)


def build_import_preview(uploaded_df: pd.DataFrame, current_df: pd.DataFrame):
    sanitized = uploaded_df.copy()
    sanitized.columns = [str(col).strip() for col in sanitized.columns]
    if "nm_id" not in sanitized.columns:
        raise ValueError("В файле обязательно должна быть колонка nm_id.")

    provided_columns = [column for column in sanitized.columns if column in IMPORTABLE_COLUMNS and column != "nm_id"]
    ignored_columns = [column for column in sanitized.columns if column not in IMPORTABLE_COLUMNS]
    if not provided_columns:
        raise ValueError("В файле нет ни одной изменяемой колонки.")

    current_map = {int(row["nm_id"]): row for row in current_df[IMPORTABLE_COLUMNS].to_dict(orient="records")}
    preview_rows = []
    changed_records = []
    errors = []

    for idx, row in sanitized.iterrows():
        row_number = idx + 2
        raw_nm_id = row.get("nm_id")
        if pd.isna(raw_nm_id):
            errors.append({"Строка": row_number, "Ошибка": "Пустой nm_id"})
            continue
        try:
            nm_id = int(float(raw_nm_id))
        except (TypeError, ValueError):
            errors.append({"Строка": row_number, "Ошибка": f"Некорректный nm_id: {raw_nm_id}"})
            continue

        current_item = current_map.get(nm_id)
        if not current_item:
            errors.append({"Строка": row_number, "Ошибка": f"Товар с nm_id={nm_id} не найден в базе"})
            continue

        merged_item = dict(current_item)
        change_labels = []
        for column in provided_columns:
            raw_value = row.get(column)
            if pd.isna(raw_value):
                continue
            try:
                normalized_value = normalize_import_value(column, raw_value)
            except ValueError as exc:
                errors.append({"Строка": row_number, "Ошибка": f"{column}: {exc}"})
                change_labels = []
                break
            current_value = merged_item.get(column)
            if not values_equal(current_value, normalized_value):
                change_labels.append(f"{column}: {display_value(current_value)} -> {display_value(normalized_value)}")
                merged_item[column] = normalized_value
        if not change_labels:
            continue
        changed_records.append(merged_item)
        preview_rows.append({"Строка": row_number, "Артикул": nm_id, "Товар": current_item.get("name"), "Изменения": " | ".join(change_labels)})

    return changed_records, preview_rows, errors, ignored_columns


st.set_page_config(page_title="Настройки товаров", page_icon="⚙️", layout="wide")
st.title("⚙️ Настройки товаров и Price Lock")
st.markdown(
    """
Здесь задаются себестоимость, минимальная/желаемая прибыль и жесткая цена WB.  
Автоматически программа исправляет только отклонение от `locked_final_price`; все расчетные цены остаются рекомендациями в аналитике.
"""
)

col_import, col_save, col_spacer = st.columns([1, 1, 3])
with col_import:
    if st.button("📥 Импорт из Wildberries", use_container_width=True):
        with st.spinner("Синхронизация карточек и текущих цен WB..."):
            success = APIClient.import_from_wb()
            if success:
                st.success("Номенклатура обновлена.")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Ошибка импорта.")

items_data = APIClient.get_items()
repricer_status = APIClient.get_repricer_status()
status_map = {item["nm_id"]: item for item in repricer_status}

if not items_data:
    st.info("База пуста. Нажмите 'Импорт из Wildberries', чтобы загрузить товары.")
    st.stop()

df = pd.DataFrame(items_data)
for column in IMPORTABLE_COLUMNS:
    if column not in df.columns:
        df[column] = None
persist_columns = list(df.columns)

df["auto_ready"] = df["nm_id"].map(lambda nm_id: "Да" if status_map.get(nm_id, {}).get("auto_ready") else "Нет")
df["auto_reason"] = df["nm_id"].map(lambda nm_id: status_map.get(nm_id, {}).get("reason_label", "Нет данных"))

active_items = int(df["is_active"].sum()) if "is_active" in df.columns else 0
locked_items = int(df["price_lock_enabled"].sum()) if "price_lock_enabled" in df.columns else 0
ready_items = int((df["auto_ready"] == "Да").sum())

m1, m2, m3, m4 = st.columns(4)
m1.metric("Товаров", len(df))
m2.metric("Активных", active_items)
m3.metric("С Price Lock", locked_items)
m4.metric("Готово к фиксации", ready_items)
st.caption("Для фиксации цены товар должен быть активен, иметь включенный price_lock_enabled, locked_final_price и locked_discount.")

st.subheader("📤 Импорт и экспорт")
export_df = df[[col for col in EXPORT_COLUMNS if col in df.columns]].copy()
export_col_csv, export_col_xlsx = st.columns(2)
with export_col_csv:
    st.download_button("⬇️ Скачать CSV", data=to_csv_bytes(export_df), file_name="wb_items_settings.csv", mime="text/csv", use_container_width=True)
with export_col_xlsx:
    st.download_button("⬇️ Скачать Excel", data=to_excel_bytes(export_df), file_name="wb_items_settings.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

uploaded_file = st.file_uploader("Загрузите CSV или Excel для массового обновления параметров", type=["csv", "xlsx", "xls"])
if uploaded_file is not None:
    try:
        uploaded_df = load_uploaded_table(uploaded_file)
        changed_records, preview_rows, import_errors, ignored_columns = build_import_preview(uploaded_df, df)
        if ignored_columns:
            st.caption(f"Игнорируемые колонки: {', '.join(ignored_columns)}")
        if import_errors:
            st.warning(f"Найдено ошибок: {len(import_errors)}")
            st.dataframe(pd.DataFrame(import_errors), use_container_width=True, hide_index=True)
        if preview_rows:
            st.success(f"Готово к обновлению: {len(changed_records)} товаров")
            st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)
            if st.button(f"📥 Применить импорт ({len(changed_records)} шт)", type="primary", use_container_width=True):
                with st.spinner("Применяю импорт..."):
                    result = APIClient.bulk_save_items(changed_records)
                    if result:
                        st.success(f"Импорт выполнен: всего {result.get('total', 0)}, создано {result.get('created', 0)}, обновлено {result.get('updated', 0)}.")
                        time.sleep(1.2)
                        st.rerun()
        elif not import_errors:
            st.info("В файле нет изменений относительно текущих данных.")
    except Exception as exc:
        st.error(f"Не удалось обработать файл: {exc}")

st.subheader("📋 Редактор параметров")
st.caption("Дважды кликните по ячейке, измените значение и нажмите 'Сохранить изменения'.")

gb = GridOptionsBuilder.from_dataframe(df)
gb.configure_default_column(resizable=True, filterable=True, sortable=True, editable=False)
for col in ["photo_url", "updated_at"]:
    if col in df.columns:
        gb.configure_column(col, hide=True)

gb.configure_column("nm_id", header_name="Артикул WB", pinned="left", width=115)
gb.configure_column("name", header_name="Название", pinned="left", width=250)
gb.configure_column("vendor_code", header_name="Артикул продавца", width=150, editable=True)

# Экономика
for col, label in {
    "cost_price": "Себестоимость",
    "min_profit_rub": "Мин. прибыль",
    "desired_profit_rub": "Желаемая прибыль",
    "logistics_cost": "План. логистика",
    "return_cost_per_unit": "Возвраты / шт",
    "ads_cost_per_unit": "Реклама / шт",
    "overhead_per_unit": "Накладные / шт",
    "wb_commission": "Комиссия WB",
    "tax_rate": "Налог",
}.items():
    if col in df.columns:
        gb.configure_column(col, header_name=label, editable=True, type=["numericColumn"])

# Price Lock
for col, label in {
    "price_lock_enabled": "Price Lock",
    "locked_final_price": "Фикс. цена клиента",
    "locked_discount": "Фикс. скидка %",
    "price_tolerance_rub": "Допуск ₽",
    "pricing_strategy": "Стратегия",
    "is_active": "Активен",
}.items():
    if col in df.columns:
        gb.configure_column(col, header_name=label, editable=True)

if "pricing_strategy" in df.columns:
    gb.configure_column("pricing_strategy", cellEditor="agSelectCellEditor", cellEditorParams={"values": sorted(STRATEGY_VALUES)})
if "repricer_mode" in df.columns:
    gb.configure_column("repricer_mode", header_name="Legacy режим", editable=True, cellEditor="agSelectCellEditor", cellEditorParams={"values": sorted(MODE_VALUES)})

for col, label in {"wb_price_base": "WB базовая", "wb_discount": "WB скидка", "wb_price_final": "WB цена", "auto_ready": "Готов", "auto_reason": "Комментарий"}.items():
    if col in df.columns:
        gb.configure_column(col, header_name=label, editable=False)

grid_response = AgGrid(
    df,
    gridOptions=gb.build(),
    data_return_mode=DataReturnMode.AS_INPUT,
    update_mode=GridUpdateMode.MODEL_CHANGED,
    fit_columns_on_grid_load=False,
    theme="balham",
    height=620,
)

with col_save:
    if st.button("💾 Сохранить изменения", type="primary", use_container_width=True):
        updated_df = grid_response["data"]
        records = updated_df.to_dict(orient="records")
        records = [{key: item.get(key) for key in persist_columns} for item in records]
        with st.spinner("Сохраняю изменения..."):
            result = APIClient.bulk_save_items(records)
        if result:
            st.success(f"Сохранение завершено: всего {result.get('total', 0)}, создано {result.get('created', 0)}, обновлено {result.get('updated', 0)}.")
            time.sleep(1.2)
            st.rerun()
        else:
            st.warning("Не удалось сохранить изменения. Проверьте логи.")
