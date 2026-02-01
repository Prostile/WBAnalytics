import streamlit as st
import requests
import pandas as pd
import time
import plotly.express as px
import plotly.graph_objects as go

# --- КОНФИГУРАЦИЯ ---
BACKEND_URL = "http://backend:8000"
st.set_page_config(page_title="WB ERP System", layout="wide", page_icon="🚀")

# --- CSS СТИЛИ ---
st.markdown("""
<style>
    .stMetric {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    }
    div[data-testid="stExpander"] div[role="button"] p {
        font-size: 1.1rem;
        font-weight: 600;
    }
    .stButton button {
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)

st.title("🚀 WB ERP: Центр управления")

# --- МЕНЮ ВКЛАДОК ---
tab_repricer, tab_settings, tab_finance = st.tabs([
    "💰 Умный Репрайсер", 
    "⚙️ Настройки Товаров", 
    "📊 Финансы (P&L)"
])

# ==============================================================================
# ВКЛАДКА 1: РЕПРАЙСЕР (UNIT ECONOMICS & CONTROL)
# ==============================================================================
with tab_repricer:
    st.header("Анализ Цен и Доходности")
    
    col_info, col_refresh = st.columns([4, 1])
    with col_info:
        st.info("💡 Система сравнивает вашу **Целевую Прибыль** с Фактом. Если расхождение большое — предлагает новую цену.")
    with col_refresh:
        if st.button("🔄 Обновить данные", key="refresh_repricer"):
            st.rerun()

    # 1. ЗАГРУЗКА ДАННЫХ
    try:
        res = requests.get(f"{BACKEND_URL}/repricer/status")
        if res.status_code != 200:
            st.error(f"Ошибка бэкенда: {res.status_code}")
            st.stop()
            
        items = res.json()
        
        if items:
            df = pd.DataFrame(items)
            
            # --- МЕТРИКИ (KPI) ---
            m1, m2, m3, m4 = st.columns(4)
            
            bad_items = df[df['status'] != 'OK']
            total_potential = bad_items['target_profit'].sum() - bad_items['current_profit'].sum()
            
            m1.metric("Всего товаров", len(df))
            m2.metric("Требуют внимания", f"{len(bad_items)} шт", delta_color="inverse")
            m3.metric("Упущенная прибыль", f"{total_potential:,.0f} ₽", help="Сумма, которую мы недополучаем из-за неправильных цен")
            
            # Средняя маржа (простая оценка)
            avg_margin = (df['current_profit'].sum() / df['current_price'].sum() * 100) if df['current_price'].sum() > 0 else 0
            m4.metric("Средняя рентабельность", f"{avg_margin:.1f}%")

            st.divider()

            # --- ТАБЛИЦА РЕКОМЕНДАЦИЙ ---
            st.subheader("📋 Рекомендации по ценам")
            st.caption("Колонка **'Будет для Клиента'** — это цена, по которой товар купит клиент (с учетом СПП и Скидки). **'Отправим на WB'** — это техническая цена до скидки.")
            
            display_df = df.copy()

            edited_df = st.data_editor(
                display_df,
                column_config={
                    "photo_url": st.column_config.ImageColumn("Фото", width="small"),
                    "nm_id": st.column_config.NumberColumn("Артикул", format="%d"),
                    
                    # ТЕКУЩЕЕ СОСТОЯНИЕ
                    "wb_discount": st.column_config.NumberColumn("Ваша Скидка", format="%d%%"),
                    "current_price": st.column_config.NumberColumn("Цена Клиента (Сейчас)", format="%.0f ₽"),
                    "current_profit": st.column_config.NumberColumn("Прибыль (Сейчас)", format="%.0f ₽"),
                    
                    # ЦЕЛЬ
                    "target_profit": st.column_config.NumberColumn("ЦЕЛЬ Прибыли", format="%.0f ₽"),
                    
                    # РЕШЕНИЕ СИСТЕМЫ
                    "recommended_price_final": st.column_config.NumberColumn(
                        "Будет для Клиента", 
                        format="%.0f ₽", 
                        help="По этой цене товар будет продаваться (Целевая цена)"
                    ),
                    "recommended_price_retail": st.column_config.NumberColumn(
                        "Отправим на WB (До скидки)", 
                        format="%.0f ₽", 
                        help="Именно эту цену мы установим в карточке, чтобы после вычета скидки получилось верно."
                    ),
                    
                    "status": st.column_config.TextColumn("Статус"),
                    "apply": st.column_config.CheckboxColumn("Выбрать", default=False) 
                },
                column_order=[
                    "photo_url", "nm_id", "wb_discount", 
                    "current_price", "current_profit", 
                    "target_profit", 
                    "recommended_price_final", # Визуально
                    "recommended_price_retail", # Технически
                    "status", "apply"
                ],
                hide_index=True,
                use_container_width=True,
                height=500
            )
            
            # --- ПАНЕЛЬ ДЕЙСТВИЙ ---
            st.divider()
            st.subheader("⚡ Действия с ценами")
            
            act_col1, act_col2, act_col3 = st.columns(3)
            
            # КНОПКА 1: ПРИМЕНИТЬ РЕКОМЕНДАЦИИ
            with act_col1:
                if st.button("✅ Применить ВСЕ рекомендации", type="primary", use_container_width=True):
                    to_update = []
                    # Собираем все, где есть рекомендация и статус не ОК
                    for index, row in df.iterrows():
                        if row['status'] != 'OK' and row['recommended_price_retail'] > 0:
                            to_update.append({
                                "nm_id": row['nm_id'],
                                "new_price": row['recommended_price_retail'] # ШЛЕМ ВЫСОКУЮ ЦЕНУ
                            })
                    
                    if to_update:
                        with st.spinner(f"Обновляем {len(to_update)} товаров на WB..."):
                            res_upd = requests.post(f"{BACKEND_URL}/repricer/batch_update", json=to_update)
                            if res_upd.status_code == 200:
                                st.success(f"Успешно! Обновлено {len(to_update)} товаров.")
                                time.sleep(2)
                                st.rerun()
                            else:
                                st.error("Ошибка обновления")
                    else:
                        st.warning("Нет рекомендаций для применения.")

            # КНОПКА 2: МАССОВО +5%
            with act_col2:
                if st.button("📈 Поднять ВСЕ цены на 5%", use_container_width=True):
                    to_update = []
                    for index, row in df.iterrows():
                        # Берем текущую БАЗОВУЮ цену (если бы мы её знали точно) или рассчитываем от рекомендованной
                        # Для безопасности берем рекомендованную Retail и увеличиваем
                        base = row['recommended_price_retail'] if row['recommended_price_retail'] > 0 else row['current_price'] * 2
                        new_p = int(base * 1.05)
                        to_update.append({"nm_id": row['nm_id'], "new_price": new_p})
                    
                    requests.post(f"{BACKEND_URL}/repricer/batch_update", json=to_update)
                    st.success("Команда отправлена!")

            # КНОПКА 3: МАССОВО -5%
            with act_col3:
                if st.button("📉 Опустить ВСЕ цены на 5%", use_container_width=True):
                    to_update = []
                    for index, row in df.iterrows():
                        base = row['recommended_price_retail'] if row['recommended_price_retail'] > 0 else row['current_price'] * 2
                        new_p = int(base * 0.95)
                        to_update.append({"nm_id": row['nm_id'], "new_price": new_p})
                    
                    requests.post(f"{BACKEND_URL}/repricer/batch_update", json=to_update)
                    st.success("Команда отправлена!")

        else:
            st.warning("База товаров пуста. Перейдите во вкладку 'Настройки' и нажмите Импорт.")

    except Exception as e:
        st.error(f"Ошибка соединения: {e}")


# ==============================================================================
# ВКЛАДКА 2: НАСТРОЙКИ (ВВОД ДАННЫХ)
# ==============================================================================
with tab_settings:
    st.header("⚙️ База Данных Товаров")
    st.info("Здесь вводятся константы для расчета: Себестоимость, Желаемая прибыль, Налоги.")
    
    col_imp, col_save = st.columns([1, 4])
    with col_imp:
        if st.button("🔄 Импорт из WB", type="secondary"):
            with st.spinner("Загружаем номенклатуру..."):
                requests.post(f"{BACKEND_URL}/items/import_from_wb")
                st.success("Готово")
                time.sleep(1)
                st.rerun()
        
    # Таблица редактор
    res = requests.get(f"{BACKEND_URL}/items/")
    if res.status_code == 200:
        items_data = res.json()
        df_edit = pd.DataFrame(items_data)
        
        if not df_edit.empty:
            edited = st.data_editor(
                df_edit,
                column_config={
                    "nm_id": st.column_config.NumberColumn("Артикул", disabled=True),
                    "name": st.column_config.TextColumn("Название", disabled=True),
                    "cost_price": st.column_config.NumberColumn("Себест-ть (руб)", min_value=0, step=100),
                    "target_profit": st.column_config.NumberColumn("ЦЕЛЬ Прибыли (руб)", min_value=0, step=100),
                    "wb_commission": st.column_config.NumberColumn("Комиссия (0.25)", min_value=0.0, max_value=1.0, step=0.01),
                    "tax_rate": st.column_config.NumberColumn("Налог (0.07)", min_value=0.0, max_value=0.5, step=0.01),
                    "logistics_cost": st.column_config.NumberColumn("Логистика (руб)", min_value=0, step=10),
                    "repricer_mode": st.column_config.SelectboxColumn("Режим", options=["manual", "auto"]),
                    "min_price": st.column_config.NumberColumn("Мин. порог", min_value=0)
                },
                column_order=[
                    "nm_id", "name", "cost_price", "target_profit", 
                    "wb_commission", "tax_rate", "logistics_cost", 
                    "repricer_mode", "min_price"
                ],
                hide_index=True,
                use_container_width=True,
                key="settings_editor"
            )
            
            if st.button("💾 Сохранить настройки", type="primary"):
                records = edited.to_dict(orient="records")
                progress = st.progress(0)
                for i, item in enumerate(records):
                    requests.post(f"{BACKEND_URL}/items/", json=item)
                    progress.progress((i+1)/len(records))
                st.success("Настройки сохранены! Перейдите во вкладку Репрайсер для расчета.")
        else:
            st.info("Нажмите кнопку Импорт, чтобы загрузить товары.")


# ==============================================================================
# ВКЛАДКА 3: ФИНАНСЫ (ОТЧЕТ V5)
# ==============================================================================
with tab_finance:
    st.header("📊 P&L: Финансовый Результат")
    st.caption("Данные на основе Еженедельных отчетов реализации (V5). Самый точный источник.")
    
    col_load, col_info = st.columns([1, 4])
    with col_load:
        if st.button("💰 Загрузить отчет V5", type="primary"):
            with st.spinner("Синхронизация с бухгалтерией WB..."):
                res = requests.post(f"{BACKEND_URL}/analytics/sync_finance", json={"days": 365})
                if res.status_code == 200:
                    d = res.json()
                    st.success(f"Найдено: {d['total_found']} строк.")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Ошибка загрузки")

    # ЗАГРУЗКА И АНАЛИЗ
    try:
        # 1. Загружаем Финансы
        res_fin = requests.get(f"{BACKEND_URL}/analytics/finance_dashboard")
        finance_data = res_fin.json()
        
        # 2. Загружаем Товары (для Себестоимости)
        res_items = requests.get(f"{BACKEND_URL}/items/")
        items_list = res_items.json()
        cost_map = {item['nm_id']: item['cost_price'] for item in items_list}
        name_map = {item['nm_id']: item['name'] or str(item['nm_id']) for item in items_list}

        if finance_data.get("records"):
            df = pd.DataFrame(finance_data["records"])
            
            # Обогащение
            df['cost_price'] = df['item'].map(cost_map).fillna(0)
            df['item_name'] = df['item'].map(name_map).fillna("Неизвестный")
            
            # --- РАСЧЕТ ЧИСТОЙ ПРИБЫЛИ (P&L) ---
            
            # 1. Продажи (где есть приход денег)
            # В V5 есть продажи (Продажа) и возвраты (Возврат). Возврат - это отрицательная сумма.
            # Мы просто суммируем amount.
            
            total_revenue = df['amount'].sum() # Пришло на счет
            
            # 2. Расходы
            # Себестоимость списываем только на ПРОДАЖИ (type='Продажа'). 
            # На возвратах себестоимость "возвращается" (условно), но логистика тратится.
            # Упрощенно: Cost = (Кол-во продаж - Кол-во возвратов) * Cost_Price
            
            sold_count = df[df['type'] == 'Продажа'].shape[0]
            return_count = df[df['type'] == 'Возврат'].shape[0]
            # Точный расчет по каждой строке сложнее, сделаем пока по продажам
            
            # Создадим колонку "Реальная себестоимость операции"
            # Если продажа: +Cost, Если возврат: -Cost (вернулся на склад)
            def calc_real_cost(row):
                if row['type'] == 'Продажа': return row['cost_price']
                if row['type'] == 'Возврат': return -row['cost_price']
                return 0
            
            df['real_cost'] = df.apply(calc_real_cost, axis=1)
            total_cogs = df['real_cost'].sum() # Cost of Goods Sold
            
            total_logistics = df['logistics'].sum() # Вся логистика
            
            # Доп расходы из полей (если бэкенд отдает, пока считаем что они внутри amount или logistics)
            
            net_profit = total_revenue - total_cogs - total_logistics
            
            # --- ВИЗУАЛИЗАЦИЯ ---
            
            # 1. ГЛАВНЫЕ ЦИФРЫ
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Чистая Прибыль", f"{net_profit:,.0f} ₽", help="Выплата - Себест - Логистика")
            m2.metric("Выплата WB", f"{total_revenue:,.0f} ₽")
            m3.metric("Себестоимость", f"{total_cogs:,.0f} ₽")
            m4.metric("Логистика", f"{total_logistics:,.0f} ₽")
            
            st.divider()
            
            col_chart1, col_chart2 = st.columns(2)
            
            # ГРАФИК 1: ВОДОПАД (Waterfall)
            with col_chart1:
                st.subheader("Структура расходов")
                fig = go.Figure(go.Waterfall(
                    name = "P&L", orientation = "v",
                    measure = ["relative", "relative", "relative", "total"],
                    x = ["Выплата WB", "Себестоимость", "Логистика", "Чистая Прибыль"],
                    textposition = "outside",
                    text = [f"{int(x)}" for x in [total_revenue, -total_cogs, -total_logistics, net_profit]],
                    y = [total_revenue, -total_cogs, -total_logistics, 0],
                    connector = {"line":{"color":"rgb(63, 63, 63)"}},
                ))
                st.plotly_chart(fig, use_container_width=True)
                
            # ГРАФИК 2: ТОП ТОВАРОВ
            with col_chart2:
                st.subheader("Топ товаров по Прибыли")
                df['profit'] = df['amount'] - df['real_cost'] - df['logistics']
                top_items = df.groupby('item_name')['profit'].sum().reset_index().sort_values('profit', ascending=False).head(10)
                fig_bar = px.bar(top_items, x='profit', y='item_name', orientation='h', color='profit')
                st.plotly_chart(fig_bar, use_container_width=True)
            
            # ДЕТАЛИЗАЦИЯ
            with st.expander("📄 Полная таблица операций"):
                st.dataframe(df, use_container_width=True)

        else:
            st.warning("Данных нет. Нажмите кнопку загрузки отчета.")
            
    except Exception as e:
        st.error(f"Ошибка построения отчета: {e}")