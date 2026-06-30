import math

def calculate_optimal_price(
    target_profit: float,
    cost_price: float,
    logistics: float,
    tax_rate: float,    # 0.07
    commission: float,  # 0.25
    current_discount: int # Например 40 (целевая скидка продавца)
) -> dict:
    """
    Рассчитывает цену, которую нужно поставить на WB, чтобы получить Target Profit.
    """
    
    # Формула:
    # Цена_Клиента = (Себест + Логистика + Прибыль) / (1 - Комиссия - Налог)
    
    # Важный нюанс: Налог платится с "Цены Клиента" (упрощенно), 
    # а Комиссия берется от "Розничной цены" или "Цены Клиента" (зависит от договора, сейчас чаще от Клиента).
    # Допустим, комиссия берется от Фактической цены продажи (Price Final).
    
    expenses = cost_price + logistics
    denominator = 1 - commission - tax_rate
    
    if denominator <= 0:
        return {"error": "Невозможные условия (Комиссия + Налог > 100%)"}
        
    required_final_price = (expenses + target_profit) / denominator
    
    # Округляем до красивых цифр (до 10 рублей)
    required_final_price = math.ceil(required_final_price / 10) * 10
    
    # Теперь считаем, какую "Зачеркнутую цену" (Retail Price) надо поставить, 
    # чтобы с учетом управляемой скидки продавца (current_discount) получилась эта цена.
    # Final = Retail * (1 - Discount/100)
    # Retail = Final / (1 - Discount/100)
    
    disc_factor = 1 - (current_discount / 100)
    if disc_factor <= 0:
        required_retail_price = required_final_price # Если скидка 100%, то беда
    else:
        required_retail_price = math.ceil((required_final_price / disc_factor) / 10) * 10

    return {
        "recommended_final_price": required_final_price, # За сколько продавать
        "recommended_retail_price": required_retail_price, # Что ставить в карточке
        "projected_profit": target_profit,
        "details": {
            "cost": cost_price,
            "logistics": logistics,
            "commission_rub": required_final_price * commission,
            "tax_rub": required_final_price * tax_rate
        }
    }
