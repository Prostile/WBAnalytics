import math
from typing import Dict


def normalize_discount(discount: int | float | None) -> int:
    try:
        value = int(float(discount if discount is not None else 0))
    except (TypeError, ValueError):
        value = 0
    return max(0, min(value, 99))


def round_price_up(price: float, step: int = 10) -> int:
    if price <= 0:
        return 0
    return int(math.ceil(price / step) * step)


def round_price_down(price: float, step: int = 10) -> int:
    if price <= 0:
        return 0
    return int(math.floor(price / step) * step)


def final_price_from_base(base_price: float, discount: int | float | None) -> float:
    factor = 1 - (normalize_discount(discount) / 100)
    if factor <= 0:
        return float(base_price or 0)
    return float(base_price or 0) * factor


def base_price_for_final(final_price: float, discount: int | float | None, step: int = 10) -> int:
    factor = 1 - (normalize_discount(discount) / 100)
    if factor <= 0:
        return round_price_up(final_price, step)
    return round_price_up(float(final_price or 0) / factor, step)


def calculate_profit_at_price(
    final_price: float,
    cost_price: float,
    logistics: float,
    tax_rate: float,
    commission: float,
    return_cost_per_unit: float = 0.0,
    ads_cost_per_unit: float = 0.0,
    overhead_per_unit: float = 0.0,
) -> float:
    """Расчет управленческой прибыли при заданной продавцовой цене WB.

    Цена является входом. Прибыль — результат. Это защищает бренд от ситуации,
    когда желаемая прибыль автоматически разгоняет цену выше допустимого уровня.
    """

    price = float(final_price or 0)
    fixed_costs = (
        float(cost_price or 0)
        + float(logistics or 0)
        + float(return_cost_per_unit or 0)
        + float(ads_cost_per_unit or 0)
        + float(overhead_per_unit or 0)
    )
    variable_costs = price * (float(tax_rate or 0) + float(commission or 0))
    return price - fixed_costs - variable_costs


def calculate_min_viable_price(
    min_profit_rub: float,
    cost_price: float,
    logistics: float,
    tax_rate: float,
    commission: float,
    return_cost_per_unit: float = 0.0,
    ads_cost_per_unit: float = 0.0,
    overhead_per_unit: float = 0.0,
) -> float:
    fixed_costs = (
        float(cost_price or 0)
        + float(logistics or 0)
        + float(return_cost_per_unit or 0)
        + float(ads_cost_per_unit or 0)
        + float(overhead_per_unit or 0)
    )
    denominator = 1 - float(tax_rate or 0) - float(commission or 0)
    if denominator <= 0:
        return 0.0
    return (fixed_costs + float(min_profit_rub or 0)) / denominator


def build_price_recommendation(
    *,
    locked_final_price: float,
    locked_discount: int,
    current_profit_per_unit: float,
    min_profit_rub: float,
    desired_profit_rub: float,
    cost_price: float,
    logistics: float,
    tax_rate: float,
    commission: float,
    return_cost_per_unit: float = 0.0,
    ads_cost_per_unit: float = 0.0,
    overhead_per_unit: float = 0.0,
    max_final_price: float = 0.0,
) -> Dict[str, float | int | str]:
    min_viable_price = calculate_min_viable_price(
        min_profit_rub=min_profit_rub,
        cost_price=cost_price,
        logistics=logistics,
        tax_rate=tax_rate,
        commission=commission,
        return_cost_per_unit=return_cost_per_unit,
        ads_cost_per_unit=ads_cost_per_unit,
        overhead_per_unit=overhead_per_unit,
    )
    rounded_min_viable = round_price_up(min_viable_price)
    target_final = float(locked_final_price or 0)
    recommended_final = target_final if target_final > 0 else rounded_min_viable
    reason_code = "hold_locked_price"
    severity = "ok"
    reason_text = "Зафиксированная цена экономически допустима."

    if min_profit_rub > 0 and current_profit_per_unit < min_profit_rub:
        recommended_final = max(rounded_min_viable, target_final)
        reason_code = "profit_below_minimum"
        severity = "critical" if current_profit_per_unit < 0 else "warning"
        reason_text = "Прибыль ниже минимального порога. Рекомендация только информационная, цена автоматически не меняется."

    if desired_profit_rub > 0 and current_profit_per_unit < desired_profit_rub and reason_code == "hold_locked_price":
        reason_code = "profit_below_desired"
        severity = "info"
        reason_text = "Прибыль ниже желаемой, но выше минимального порога."

    if max_final_price > 0 and recommended_final > max_final_price:
        reason_code = "economics_above_price_ceiling"
        severity = "critical"
        reason_text = "Минимально жизнеспособная цена выше заданного верхнего ценового потолка."
        recommended_final = max_final_price

    return {
        "recommended_final_price": float(recommended_final or 0),
        "recommended_base_price": base_price_for_final(float(recommended_final or 0), locked_discount),
        "recommended_discount": normalize_discount(locked_discount),
        "min_viable_price": float(rounded_min_viable or 0),
        "projected_profit_per_unit": calculate_profit_at_price(
            float(recommended_final or 0),
            cost_price,
            logistics,
            tax_rate,
            commission,
            return_cost_per_unit,
            ads_cost_per_unit,
            overhead_per_unit,
        ),
        "reason_code": reason_code,
        "reason_text": reason_text,
        "severity": severity,
    }


def calculate_optimal_price(
    target_profit: float,
    cost_price: float,
    logistics: float,
    tax_rate: float,
    commission: float,
    current_discount: int,
) -> dict:
    """Legacy-функция для совместимости старого UI.

    Новая автоматизация не должна использовать target_profit как основание для
    изменения цены. Для аналитики и рекомендаций используйте функции выше.
    """

    denominator = 1 - commission - tax_rate
    if denominator <= 0:
        return {"error": "Невозможные условия (Комиссия + Налог > 100%)"}

    required_final_price = round_price_up((float(cost_price or 0) + float(logistics or 0) + float(target_profit or 0)) / denominator)
    required_retail_price = base_price_for_final(required_final_price, current_discount)

    return {
        "recommended_final_price": required_final_price,
        "recommended_retail_price": required_retail_price,
        "projected_profit": target_profit,
        "details": {
            "cost": cost_price,
            "logistics": logistics,
            "commission_rub": required_final_price * commission,
            "tax_rub": required_final_price * tax_rate,
        },
    }
