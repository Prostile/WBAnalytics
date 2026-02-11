import pandas as pd
import numpy as np

def process_raw_finance_data(records: list, items_map: dict) -> pd.DataFrame:
    """Обогащает сырые данные из API: добавляет названия, считает COGS и прибыль по каждой строке."""
    df = pd.DataFrame(records)
    if df.empty:
        return df
    
    df['date'] = pd.to_datetime(df['date'])
    df['item_name'] = df['item'].map(lambda x: items_map.get(x, {}).get('name', str(x)))
    df['cost_unit'] = df['item'].map(lambda x: items_map.get(x, {}).get('cost_price', 0))
    
    # Считаем реальную себестоимость операции
    def calc_real_cost(row):
        if row['type'] == 'Продажа': return row['cost_unit']
        if row['type'] == 'Возврат': return -row['cost_unit']
        return 0
        
    df['real_cogs'] = df.apply(calc_real_cost, axis=1)
    
    # Защита от старых данных, если retail_amount не пришел
    if 'retail_amount' not in df.columns:
        df['retail_amount'] = df['amount']
        
    # Чистая прибыль по конкретной транзакции
    df['profit'] = df['amount'] - df['real_cogs'] - df['logistics']
    
    return df

def calculate_global_kpis(df: pd.DataFrame) -> dict:
    """Считает общие показатели (KPI) для верхнего дашборда."""
    if df.empty:
        return {
            "gross_revenue": 0, "net_revenue": 0, "wb_commission": 0,
            "cogs": 0, "logistics": 0, "net_profit": 0, "margin": 0
        }
        
    gross_revenue = df['retail_amount'].sum()
    net_revenue = df['amount'].sum()
    cogs = df['real_cogs'].sum()
    logistics = df['logistics'].sum()
    net_profit = df['profit'].sum()
    
    margin = (net_profit / gross_revenue * 100) if gross_revenue > 0 else 0
    wb_commission = gross_revenue - net_revenue
    
    return {
        "gross_revenue": gross_revenue,
        "net_revenue": net_revenue,
        "wb_commission": wb_commission,
        "cogs": cogs,
        "logistics": logistics,
        "net_profit": net_profit,
        "margin": margin
    }

def build_abc_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """Собирает сложную таблицу Unit-экономики по каждому товару."""
    if df.empty:
        return pd.DataFrame()
    
    # Разделяем продажи и возвраты для точного подсчета штук
    sales_df = df[df['type'] == 'Продажа']
    returns_df = df[df['type'] == 'Возврат']
    
    sales_counts = sales_df.groupby('item_name').size().rename('sales_qty')
    returns_counts = returns_df.groupby('item_name').size().rename('returns_qty')
    
    # Агрегируем финансы
    fin_agg = df.groupby('item_name').agg({
        'retail_amount': 'sum',
        'amount': 'sum',
        'real_cogs': 'sum',
        'logistics': 'sum',
        'profit': 'sum'
    })
    
    # Объединяем штуки и финансы
    abc = fin_agg.join(sales_counts, how='outer').join(returns_counts, how='outer').fillna(0)
    
    # --- НОВЫЕ МЕТРИКИ (Глубокая аналитика) ---
    
    # 1. Процент выкупа (Return Rate)
    # Если продаж > 0, считаем процент возвратов. Иначе 0.
    abc['return_rate_pct'] = np.where(abc['sales_qty'] > 0, (abc['returns_qty'] / abc['sales_qty'] * 100), 0)
    
    # 2. Чистое количество проданных единиц (Продали минус Вернули)
    abc['net_qty'] = abc['sales_qty'] - abc['returns_qty']
    
    # 3. Юнит-экономика: Чистая прибыль с 1 единицы товара
    abc['profit_per_unit'] = np.where(abc['net_qty'] > 0, abc['profit'] / abc['net_qty'], 0)
    
    # 4. Доля комиссии WB
    abc['wb_commission'] = abc['retail_amount'] - abc['amount']
    
    # Сортируем от самых прибыльных к самым убыточным
    abc = abc.sort_values('profit', ascending=False).reset_index()
    
    return abc

def get_daily_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Агрегация по дням для графика трендов."""
    if df.empty:
        return pd.DataFrame()
        
    trend = df.groupby('date').agg({
        'retail_amount': 'sum',
        'profit': 'sum'
    }).reset_index()
    return trend