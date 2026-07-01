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


from utils.ui_theme import apply_fintech_theme, integer, money, render_header, render_metric_strip, section


st.set_page_config(page_title="Настройки товаров", page_icon="⚙️", layout="wide")
apply_fintech_theme()

with st.sidebar:
    st.markdown("### Действия")
    if st.button("Импорт из Wildberries", use_container_width=True, key="settings_import_wb"):
        with st.spinner("Синхронизация карточек и текущих цен WB..."):
            success = APIClient.import_from_wb()
            if success:
                st.success("Номенклатура обновлена.")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Ошибка импорта.")
    st.caption("Редактирование параметров разбито на вкладки, чтобы таблица не превращалась в нечитаемый набор колонок.")

render_header(
    title="Настройки товаров и Price Lock",
    subtitle="Здесь задаются себестоимость, минимальная/желаемая прибыль и жёсткая продавцовая цена WB. Автоматика исправляет только отклонение от locked_final_price.",
    overline="Product settings",
)

items_data = APIClient.get_items()
repricer_status = APIClient.get_repricer_status()
status_map = {item["nm_id"]: item for item in repricer_status}

if not items_data:
    st.info("База пуста. Нажмите 'Импорт из Wildberries' в боковой панели, чтобы загрузить товары.")
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

render_metric_strip(
    [
        {"label": "Товаров", "value": integer(len(df)), "note": "в базе"},
        {"label": "Активных", "value": integer(active_items), "note": "участвуют в расчётах"},
        {"label": "С Price Lock", "value": integer(locked_items), "note": "включена фиксация"},
        {"label": "Готово", "value": integer(ready_items), "note": "есть цена и скидка"},
        {"label": "Не готовы", "value": integer(max(len(df) - ready_items, 0)), "note": "требуют настройки"},
    ]
)

section("Импорт и экспорт", "CSV/Excel остаются для массового обновления параметров. Редактор ниже разбит на смысловые таблицы.")
with st.expander("Открыть импорт / экспорт", expanded=False):
    export_df = df[[col for col in EXPORT_COLUMNS if col in df.columns]].copy()
    export_col_csv, export_col_xlsx = st.columns(2)
    with export_col_csv:
        st.download_button("Скачать CSV", data=to_csv_bytes(export_df), file_name="wb_items_settings.csv", mime="text/csv", use_container_width=True, key="settings_download_csv")
    with export_col_xlsx:
        st.download_button("Скачать Excel", data=to_excel_bytes(export_df), file_name="wb_items_settings.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key="settings_download_xlsx")

    uploaded_file = st.file_uploader("Загрузите CSV или Excel для массового обновления параметров", type=["csv", "xlsx", "xls"], key="settings_upload_file")
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
                if st.button(f"Применить импорт ({len(changed_records)} шт.)", type="primary", use_container_width=True, key="settings_apply_import"):
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

section("Редактор параметров", "Не выводим все поля в одной таблице. Настройки разделены на базовые данные, экономику, Price Lock и состояние WB.")

EDIT_SETS = {
    "Базовые": ["nm_id", "name", "vendor_code", "is_active"],
    "Экономика": ["nm_id", "name", "cost_price", "logistics_cost", "return_cost_per_unit", "ads_cost_per_unit", "overhead_per_unit", "min_profit_rub", "desired_profit_rub", "wb_commission", "tax_rate"],
    "Price Lock": ["nm_id", "name", "price_lock_enabled", "locked_final_price", "locked_discount", "price_tolerance_rub", "pricing_strategy", "repricer_mode", "auto_ready", "auto_reason"],
    "WB состояние": ["nm_id", "name", "wb_price_base", "wb_discount", "wb_price_final", "target_discount", "min_price", "max_price", "auto_ready", "auto_reason"],
}

EDITABLE_BY_TAB = {
    "Базовые": {"name", "vendor_code", "is_active"},
    "Экономика": {"cost_price", "logistics_cost", "return_cost_per_unit", "ads_cost_per_unit", "overhead_per_unit", "min_profit_rub", "desired_profit_rub", "wb_commission", "tax_rate"},
    "Price Lock": {"price_lock_enabled", "locked_final_price", "locked_discount", "price_tolerance_rub", "pricing_strategy", "repricer_mode"},
    "WB состояние": {"target_discount", "min_price", "max_price"},
}

updated_frames: dict[str, pd.DataFrame] = {}

def configure_grid(subset: pd.DataFrame, tab_key: str):
    gb = GridOptionsBuilder.from_dataframe(subset)
    gb.configure_default_column(resizable=True, filterable=True, sortable=True, editable=False, wrapHeaderText=True, autoHeaderHeight=True)
    gb.configure_grid_options(rowHeight=42, headerHeight=44, enableCellTextSelection=True, ensureDomOrder=True, suppressHorizontalScroll=False)
    gb.configure_column("nm_id", header_name="nmID", pinned="left", width=98, editable=False)
    if "name" in subset.columns:
        gb.configure_column("name", header_name="Товар", pinned="left", width=260, editable=True if tab_key == "basic" else False, tooltipField="name")
    if "vendor_code" in subset.columns:
        gb.configure_column("vendor_code", header_name="Артикул продавца", width=165, editable=True)
    if "is_active" in subset.columns:
        gb.configure_column("is_active", header_name="Активен", width=95, editable=True)

    labels = {
        "cost_price": "Себестоимость",
        "logistics_cost": "План. логистика",
        "return_cost_per_unit": "Возвраты / шт",
        "ads_cost_per_unit": "Реклама / шт",
        "overhead_per_unit": "Накладные / шт",
        "min_profit_rub": "Мин. прибыль",
        "desired_profit_rub": "Желаемая прибыль",
        "wb_commission": "Комиссия WB",
        "tax_rate": "Налог",
        "locked_final_price": "Фикс. цена",
        "locked_discount": "Фикс. скидка %",
        "price_tolerance_rub": "Допуск ₽",
        "pricing_strategy": "Стратегия",
        "repricer_mode": "Legacy режим",
        "price_lock_enabled": "Price Lock",
        "wb_price_base": "WB база",
        "wb_discount": "WB скидка",
        "wb_price_final": "WB цена",
        "target_discount": "Legacy скидка",
        "min_price": "Legacy мин.",
        "max_price": "Legacy макс.",
        "auto_ready": "Готов",
        "auto_reason": "Комментарий",
    }
    money_like = {"cost_price", "logistics_cost", "return_cost_per_unit", "ads_cost_per_unit", "overhead_per_unit", "min_profit_rub", "desired_profit_rub", "locked_final_price", "price_tolerance_rub", "wb_price_base", "wb_price_final", "min_price", "max_price"}
    percent_like = {"wb_commission", "tax_rate", "locked_discount", "target_discount", "wb_discount"}

    for col, label in labels.items():
        if col not in subset.columns:
            continue
        editable = col not in {"wb_price_base", "wb_discount", "wb_price_final", "auto_ready", "auto_reason"}
        width = 136
        params = {"header_name": label, "width": width, "editable": editable}
        if col in money_like:
            params.update({"type": ["numericColumn"], "valueFormatter": "x == null ? '' : x.toLocaleString('ru-RU') + ' ₽'"})
        if col in percent_like:
            params.update({"type": ["numericColumn"], "valueFormatter": "x == null ? '' : x.toLocaleString('ru-RU') + ' %'"})
        if col in {"pricing_strategy", "repricer_mode", "auto_reason"}:
            params["width"] = 210 if col != "auto_reason" else 340
            params["tooltipField"] = col
        gb.configure_column(col, **params)

    if "pricing_strategy" in subset.columns:
        gb.configure_column("pricing_strategy", cellEditor="agSelectCellEditor", cellEditorParams={"values": sorted(STRATEGY_VALUES)})
    if "repricer_mode" in subset.columns:
        gb.configure_column("repricer_mode", cellEditor="agSelectCellEditor", cellEditorParams={"values": sorted(MODE_VALUES)})

    response = AgGrid(
        subset,
        gridOptions=gb.build(),
        data_return_mode=DataReturnMode.AS_INPUT,
        update_mode=GridUpdateMode.MODEL_CHANGED,
        fit_columns_on_grid_load=False,
        theme="balham",
        height=540,
        key=f"settings_grid_{tab_key}",
    )
    return pd.DataFrame(response["data"])

tabs = st.tabs(list(EDIT_SETS.keys()))
for tab, (label, columns) in zip(tabs, EDIT_SETS.items()):
    with tab:
        available_columns = [col for col in columns if col in df.columns]
        tab_df = df[available_columns].copy()
        updated_frames[label] = configure_grid(tab_df, label.lower().replace(" ", "_"))

save_col, info_col = st.columns([1, 4])
with save_col:
    if st.button("Сохранить изменения", type="primary", use_container_width=True, key="settings_save_all"):
        merged_df = df.copy()
        for label, frame in updated_frames.items():
            if frame.empty or "nm_id" not in frame.columns:
                continue
            editable_cols = [col for col in frame.columns if col in EDITABLE_BY_TAB.get(label, set()) and col in persist_columns]
            indexed_frame = frame.set_index("nm_id")
            for col in editable_cols:
                merged_df[col] = merged_df["nm_id"].map(indexed_frame[col]).where(merged_df["nm_id"].isin(indexed_frame.index), merged_df[col])
        records = merged_df[persist_columns].to_dict(orient="records")
        with st.spinner("Сохраняю изменения..."):
            result = APIClient.bulk_save_items(records)
        if result:
            st.success(f"Сохранение завершено: всего {result.get('total', 0)}, создано {result.get('created', 0)}, обновлено {result.get('updated', 0)}.")
            time.sleep(1.2)
            st.rerun()
        else:
            st.warning("Не удалось сохранить изменения. Проверьте логи.")
with info_col:
    st.markdown("<div class='side-panel-muted'>Для фиксации цены товар должен быть активен, иметь включенный Price Lock, locked_final_price и locked_discount. Экономические поля влияют только на аналитику и рекомендации.</div>", unsafe_allow_html=True)
