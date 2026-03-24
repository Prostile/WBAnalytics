import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode
import time
import os
import sys
from io import BytesIO

# Подключаем наш API-клиент
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.api_client import APIClient

IMPORTABLE_COLUMNS = [
    "nm_id",
    "vendor_code",
    "name",
    "cost_price",
    "target_profit",
    "min_price",
    "wb_commission",
    "logistics_cost",
    "tax_rate",
    "repricer_mode",
    "is_active",
]

EXPORT_COLUMNS = IMPORTABLE_COLUMNS + ["auto_ready", "auto_reason"]
NUMERIC_COLUMNS = {"cost_price", "target_profit", "min_price", "wb_commission", "logistics_cost", "tax_rate"}
BOOLEAN_COLUMNS = {"is_active"}
TEXT_COLUMNS = {"vendor_code", "name"}
MODE_VALUES = {"manual", "auto"}


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
            raise ValueError("режим должен быть manual или auto")
        return normalized

    if column in TEXT_COLUMNS:
        return str(value).strip()

    return value


def values_equal(left, right) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        try:
            return abs(float(left) - float(right)) < 1e-9
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
                change_labels.append(
                    f"{column}: {display_value(current_value)} -> {display_value(normalized_value)}"
                )
                merged_item[column] = normalized_value

        if not change_labels:
            continue

        changed_records.append(merged_item)
        preview_rows.append(
            {
                "Строка": row_number,
                "Артикул": nm_id,
                "Товар": current_item.get("name"),
                "Изменения": " | ".join(change_labels),
            }
        )

    return changed_records, preview_rows, errors, ignored_columns

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

st.subheader("📤 Импорт и Экспорт")
export_df = df[EXPORT_COLUMNS].copy()
csv_bytes = to_csv_bytes(export_df)
excel_bytes = to_excel_bytes(export_df)

export_col_csv, export_col_xlsx = st.columns(2)
with export_col_csv:
    st.download_button(
        "⬇️ Скачать CSV",
        data=csv_bytes,
        file_name="wb_items_settings.csv",
        mime="text/csv",
        use_container_width=True,
    )
with export_col_xlsx:
    st.download_button(
        "⬇️ Скачать Excel",
        data=excel_bytes,
        file_name="wb_items_settings.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

uploaded_file = st.file_uploader(
    "Загрузите CSV или Excel для массового обновления параметров",
    type=["csv", "xlsx", "xls"],
)

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
                        st.success(
                            f"Импорт выполнен: всего {result.get('total', 0)}, создано {result.get('created', 0)}, обновлено {result.get('updated', 0)}."
                        )
                        time.sleep(1.2)
                        st.rerun()
        elif not import_errors:
            st.info("В файле нет изменений относительно текущих данных.")
    except Exception as exc:
        st.error(f"Не удалось обработать файл: {exc}")

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

        with st.spinner("Сохраняю изменения..."):
            result = APIClient.bulk_save_items(records)

        if result:
            st.success(
                f"Сохранение завершено: всего {result.get('total', 0)}, создано {result.get('created', 0)}, обновлено {result.get('updated', 0)}."
            )
            time.sleep(1.5)
            st.rerun()
        else:
            st.warning("Не удалось сохранить изменения. Проверьте логи.")
