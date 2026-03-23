import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import unit_economics
from app.wb_client import wb

PROFIT_TOLERANCE_RUB = 100
MIN_AUTO_CHANGE_RUB = 10
MIN_AUTO_CHANGE_PCT = 1.0

REASON_LABELS = {
    "inactive": "Товар выключен",
    "manual_mode": "Ручной режим",
    "missing_cost_price": "Нет себестоимости",
    "missing_target_profit": "Не задана цель прибыли",
    "missing_live_price": "Нет актуальной цены WB",
    "invalid_economics": "Комиссия и налог дают некорректную формулу",
    "within_tolerance": "Отклонение в пределах допуска",
    "price_already_optimal": "Цена уже близка к расчетной",
    "change_below_threshold": "Изменение слишком маленькое",
    "target_profit_gap": "Цена ниже цели по прибыли",
    "min_price_floor_applied": "Ограничено минимальной ценой",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _final_price_from_retail(retail_price: float, discount: int) -> float:
    factor = 1 - ((discount or 0) / 100)
    if factor <= 0:
        return float(retail_price or 0)
    return float(retail_price or 0) * factor


def _current_profit(item: models.Item, final_price: float | None = None) -> float:
    effective_final = float(final_price if final_price is not None else (item.wb_price_final or 0))
    return (
        effective_final
        - float(item.cost_price or 0)
        - float(item.logistics_cost or 0)
        - (effective_final * float(item.wb_commission or 0))
        - (effective_final * float(item.tax_rate or 0))
    )


def _rounded_floor_price(price: float) -> int:
    return int(math.ceil(float(price or 0) / 10) * 10)


def _reason_label(code: str | None) -> str:
    return REASON_LABELS.get(code or "", code or "")


def build_item_decision(item: models.Item) -> Dict[str, Any]:
    current_price_retail = float(item.wb_price_base or 0)
    current_price_final = float(item.wb_price_final or 0)
    current_profit = _current_profit(item, current_price_final)

    issues: List[str] = []
    if not item.is_active:
        issues.append("inactive")
    if float(item.cost_price or 0) <= 0:
        issues.append("missing_cost_price")
    if float(item.target_profit or 0) <= 0:
        issues.append("missing_target_profit")
    if current_price_retail <= 0 or current_price_final <= 0:
        issues.append("missing_live_price")

    optimal = unit_economics.calculate_optimal_price(
        target_profit=float(item.target_profit or 0),
        cost_price=float(item.cost_price or 0),
        logistics=float(item.logistics_cost or 0),
        tax_rate=float(item.tax_rate or 0),
        commission=float(item.wb_commission or 0),
        current_discount=int(item.wb_discount or 0),
    )

    if optimal.get("error"):
        issues.append("invalid_economics")

    recommended_price_retail = int(optimal.get("recommended_retail_price") or 0)
    recommended_price_final = float(optimal.get("recommended_final_price") or 0)
    floor_applied = False

    if float(item.min_price or 0) > 0 and recommended_price_retail > 0 and recommended_price_retail < float(item.min_price):
        recommended_price_retail = _rounded_floor_price(float(item.min_price))
        recommended_price_final = _final_price_from_retail(recommended_price_retail, int(item.wb_discount or 0))
        floor_applied = True

    projected_profit = _current_profit(item, recommended_price_final) if recommended_price_retail > 0 else current_profit
    profit_gap = float(item.target_profit or 0) - current_profit
    price_delta = recommended_price_retail - current_price_retail
    price_delta_pct = (price_delta / current_price_retail * 100) if current_price_retail > 0 else 0.0

    status = "⚪ SETUP"
    if not issues:
        status = "OK" if abs(profit_gap) <= PROFIT_TOLERANCE_RUB else "⚠️ MISMATCH"

    auto_ready = not issues and item.repricer_mode == "auto"
    should_auto_update = False
    reason_code = issues[0] if issues else "within_tolerance"

    if auto_ready:
        if profit_gap > PROFIT_TOLERANCE_RUB:
            if price_delta <= 0:
                reason_code = "price_already_optimal"
            elif abs(price_delta) < MIN_AUTO_CHANGE_RUB or abs(price_delta_pct) < MIN_AUTO_CHANGE_PCT:
                reason_code = "change_below_threshold"
            else:
                should_auto_update = True
                reason_code = "target_profit_gap"
        else:
            reason_code = "within_tolerance"
    elif not issues and item.repricer_mode != "auto":
        reason_code = "manual_mode"

    if floor_applied and should_auto_update:
        reason_code = "min_price_floor_applied"

    needs_manual_action = (
        not issues
        and item.repricer_mode == "manual"
        and profit_gap > PROFIT_TOLERANCE_RUB
        and recommended_price_retail > 0
    )

    return {
        "nm_id": item.nm_id,
        "name": item.name,
        "photo_url": item.photo_url,
        "mode": item.repricer_mode,
        "is_active": item.is_active,
        "auto_ready": auto_ready,
        "should_auto_update": should_auto_update,
        "needs_manual_action": needs_manual_action,
        "reason_code": reason_code,
        "reason_label": _reason_label(reason_code),
        "wb_discount": int(item.wb_discount or 0),
        "current_price_retail": current_price_retail,
        "current_price": current_price_final,
        "current_profit": round(current_profit, 0),
        "target_profit": float(item.target_profit or 0),
        "profit_gap": round(profit_gap, 0),
        "recommended_price_final": recommended_price_final,
        "recommended_price_retail": recommended_price_retail,
        "projected_profit": round(projected_profit, 0),
        "price_delta": round(price_delta, 0),
        "price_delta_pct": round(price_delta_pct, 2),
        "min_price": float(item.min_price or 0),
        "status": status,
    }


async def refresh_live_prices(db: AsyncSession, active_only: bool = True) -> Dict[str, int]:
    query = select(models.Item)
    if active_only:
        query = query.filter(models.Item.is_active == True)

    result = await db.execute(query)
    items = result.scalars().all()
    if not items:
        return {"updated": 0, "matched": 0, "fetched": 0}

    prices_map = wb.get_prices()
    if not prices_map:
        raise RuntimeError("WB не вернул актуальные цены для фоновой оптимизации.")

    updated = 0
    matched = 0
    for item in items:
        price_info = prices_map.get(item.nm_id)
        if not price_info:
            continue

        matched += 1
        old_snapshot = (item.wb_price_base, item.wb_discount, item.wb_price_final)
        item.wb_price_base = float(price_info.get("wb_price_base", 0) or 0)
        item.wb_discount = int(price_info.get("wb_discount", 0) or 0)
        item.wb_price_final = float(price_info.get("wb_price_final", 0) or 0)
        new_snapshot = (item.wb_price_base, item.wb_discount, item.wb_price_final)
        if new_snapshot != old_snapshot:
            updated += 1

    return {"updated": updated, "matched": matched, "fetched": len(prices_map)}


async def build_repricer_report(db: AsyncSession, active_only: bool = True) -> List[Dict[str, Any]]:
    query = select(models.Item).order_by(models.Item.nm_id)
    if active_only:
        query = query.filter(models.Item.is_active == True)

    result = await db.execute(query)
    items = result.scalars().all()
    report = [build_item_decision(item) for item in items]
    report.sort(
        key=lambda row: (
            0 if row["should_auto_update"] else 1,
            0 if row["needs_manual_action"] else 1,
            -abs(float(row["profit_gap"] or 0)),
            int(row["nm_id"]),
        )
    )
    return report


async def apply_price_updates(
    db: AsyncSession,
    updates: Iterable[Dict[str, Any]],
    *,
    source: str,
    default_reason: str,
    run_id: int | None = None,
) -> List[Dict[str, Any]]:
    normalized_updates: List[Dict[str, Any]] = []
    for update in updates:
        nm_id = int(update["nm_id"])
        new_price = int(update["new_price"])
        if new_price <= 0:
            continue
        normalized_updates.append(
            {
                "nm_id": nm_id,
                "new_price": new_price,
                "reason": update.get("reason", default_reason),
            }
        )

    if not normalized_updates:
        return []

    result = await db.execute(
        select(models.Item).filter(models.Item.nm_id.in_([u["nm_id"] for u in normalized_updates]))
    )
    items_by_nm_id = {item.nm_id: item for item in result.scalars().all()}

    planned_changes: List[Dict[str, Any]] = []
    for update in normalized_updates:
        item = items_by_nm_id.get(update["nm_id"])
        if not item:
            continue

        old_price_retail = float(item.wb_price_base or 0)
        old_price_final = float(item.wb_price_final or 0)
        new_price_retail = int(update["new_price"])
        if int(old_price_retail) == new_price_retail:
            continue

        new_price_final = _final_price_from_retail(new_price_retail, int(item.wb_discount or 0))
        old_profit = _current_profit(item, old_price_final)
        new_profit = _current_profit(item, new_price_final)
        price_delta = new_price_retail - old_price_retail
        price_delta_percent = (price_delta / old_price_retail * 100) if old_price_retail > 0 else 0.0

        planned_changes.append(
            {
                "item": item,
                "nm_id": item.nm_id,
                "name": item.name or str(item.nm_id),
                "old_price_retail": old_price_retail,
                "new_price_retail": float(new_price_retail),
                "old_price_final": old_price_final,
                "new_price_final": new_price_final,
                "old_profit": old_profit,
                "new_profit": new_profit,
                "target_profit": float(item.target_profit or 0),
                "wb_discount": int(item.wb_discount or 0),
                "price_delta": price_delta,
                "price_delta_percent": price_delta_percent,
                "reason": update["reason"],
            }
        )

    if not planned_changes:
        return []

    wb_payload = [{"nmID": change["nm_id"], "price": int(change["new_price_retail"])} for change in planned_changes]
    if not wb.update_prices(wb_payload):
        raise RuntimeError("WB не принял пакет обновления цен.")

    persisted_changes: List[Dict[str, Any]] = []
    for change in planned_changes:
        item = change.pop("item")
        item.wb_price_base = change["new_price_retail"]
        item.wb_price_final = change["new_price_final"]
        item.updated_at = _now_utc()

        db.add(
            models.PriceHistory(
                nm_id=item.nm_id,
                price_retail=change["new_price_retail"],
                discount=change["wb_discount"],
                final_price=change["new_price_final"],
            )
        )
        db.add(
            models.RepricerEvent(
                run_id=run_id,
                nm_id=item.nm_id,
                item_name=item.name,
                source=source,
                reason=change["reason"],
                old_price_retail=change["old_price_retail"],
                new_price_retail=change["new_price_retail"],
                old_price_final=change["old_price_final"],
                new_price_final=change["new_price_final"],
                old_profit=change["old_profit"],
                new_profit=change["new_profit"],
                target_profit=change["target_profit"],
                wb_discount=change["wb_discount"],
                price_delta=change["price_delta"],
                price_delta_percent=change["price_delta_percent"],
            )
        )
        persisted_changes.append(change)

    return persisted_changes


async def run_background_repricing(db: AsyncSession, source: str = "scheduler_hourly") -> Dict[str, Any]:
    run = models.RepricerRun(source=source, status="running")
    db.add(run)
    await db.commit()
    await db.refresh(run)

    try:
        price_sync = await refresh_live_prices(db, active_only=True)
        await db.commit()

        report = await build_repricer_report(db, active_only=True)
        auto_updates = [
            {
                "nm_id": row["nm_id"],
                "new_price": int(row["recommended_price_retail"]),
                "reason": row["reason_code"],
            }
            for row in report
            if row["should_auto_update"]
        ]
        manual_candidates = [row for row in report if row["needs_manual_action"]]
        auto_ready_items = [row for row in report if row["auto_ready"]]
        skipped_items = [row for row in report if not row["should_auto_update"] and not row["needs_manual_action"]]

        changes = await apply_price_updates(
            db,
            auto_updates,
            source=source,
            default_reason="target_profit_gap",
            run_id=run.id,
        )

        run = await db.get(models.RepricerRun, run.id)
        run.status = "success"
        run.finished_at = _now_utc()
        run.checked_items = len(report)
        run.eligible_items = len(auto_ready_items)
        run.changed_items = len(changes)
        run.skipped_items = len(skipped_items)
        run.manual_items = len(manual_candidates)
        run.price_sync_items = price_sync["updated"]
        run.error_message = None
        await db.commit()

        return {
            "run_id": run.id,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "checked_items": run.checked_items,
            "eligible_items": run.eligible_items,
            "changed_items": run.changed_items,
            "skipped_items": run.skipped_items,
            "manual_items": run.manual_items,
            "price_sync_items": run.price_sync_items,
            "changes": changes,
            "manual_alerts": manual_candidates,
        }
    except Exception as exc:
        await db.rollback()
        failed_run = await db.get(models.RepricerRun, run.id)
        if failed_run:
            failed_run.status = "failed"
            failed_run.finished_at = _now_utc()
            failed_run.error_message = str(exc)
            await db.commit()
        raise
