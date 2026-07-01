from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import unit_economics
from app.wb_client import wb

PRICE_LOCK_STRATEGY = "fixed_final_price"
PRICE_LOCK_STRATEGY_LABEL = "Fixed WB Price"
PRICE_LOCK_STRATEGY_DESCRIPTION = (
    "Фоновый режим автоматически исправляет только отклонение базовой цены WB "
    "и скидки продавца от зафиксированных значений. Итоговая продавцовая цена "
    "после скидки рассчитывается отдельно. Рекомендации по экономике не применяются "
    "без ручного решения."
)

REASON_LABELS = {
    "inactive": "Товар выключен",
    "price_lock_disabled": "Фиксация цены выключена",
    "missing_locked_price": "Не задана фиксированная цена",
    "missing_live_price": "Нет актуальной цены WB",
    "invalid_locked_discount": "Некорректная фиксированная скидка",
    "within_tolerance": "Цена в пределах допуска",
    "price_lock_drift": "Цена WB ушла от фиксированной",
    "profit_below_minimum": "Прибыль ниже минимального порога",
    "profit_below_desired": "Прибыль ниже желательной",
    "hold_locked_price": "Зафиксированную цену оставить",
    "economics_above_price_ceiling": "Экономика не сходится в ценовом потолке",
    "manual_apply": "Ручное применение",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _reason_label(code: str | None) -> str:
    return REASON_LABELS.get(code or "", code or "")


def _normalize_discount(discount: int | float | None) -> int:
    return unit_economics.normalize_discount(discount)


def _discount_is_valid(discount: int | float | None) -> bool:
    try:
        value = int(float(discount if discount is not None else 0))
    except (TypeError, ValueError):
        return False
    return 0 <= value <= 99


def _locked_discount(item: models.Item) -> int:
    raw_discount = item.locked_discount
    if raw_discount is None:
        raw_discount = item.target_discount if item.target_discount is not None else item.wb_discount
    return _normalize_discount(raw_discount)


def _locked_base_price(item: models.Item) -> float:
    """Return the fixed WB base/list price before seller discount.

    The database field is still named ``locked_final_price`` for backward
    compatibility with existing exports and saved settings. In the UI it must be
    treated as ``Фикс. цена WB``: the base price sent to WB API together with
    ``locked_discount``. The effective seller price is calculated as
    ``locked_base_price * (1 - locked_discount / 100)``.
    """

    if float(item.locked_final_price or 0) > 0:
        return float(item.locked_final_price or 0)
    return float(item.wb_price_base or 0)


def _locked_final_price(item: models.Item, locked_discount: int | None = None) -> float:
    discount = _locked_discount(item) if locked_discount is None else locked_discount
    return unit_economics.final_price_from_base(_locked_base_price(item), discount)


def _current_profit(item: models.Item, final_price: float | None = None) -> float:
    effective_final = float(final_price if final_price is not None else (item.wb_price_final or 0))
    return unit_economics.calculate_profit_at_price(
        final_price=effective_final,
        cost_price=float(item.cost_price or 0),
        logistics=float(item.logistics_cost or 0),
        tax_rate=float(item.tax_rate or 0),
        commission=float(item.wb_commission or 0),
        return_cost_per_unit=float(item.return_cost_per_unit or 0),
        ads_cost_per_unit=float(item.ads_cost_per_unit or 0),
        overhead_per_unit=float(item.overhead_per_unit or 0),
    )


def _serialize_run(run: models.RepricerRun | None) -> Dict[str, Any] | None:
    if not run:
        return None

    return {
        "id": run.id,
        "source": run.source,
        "status": run.status,
        "started_at": _serialize_dt(run.started_at),
        "finished_at": _serialize_dt(run.finished_at),
        "checked_items": run.checked_items,
        "eligible_items": run.eligible_items,
        "changed_items": run.changed_items,
        "skipped_items": run.skipped_items,
        "manual_items": run.manual_items,
        "price_sync_items": run.price_sync_items,
        "error_message": run.error_message,
        "next_run_at": _serialize_dt(run.started_at + timedelta(hours=1)) if run.started_at else None,
    }


def _serialize_event(event: models.RepricerEvent) -> Dict[str, Any]:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "nm_id": event.nm_id,
        "item_name": event.item_name,
        "source": event.source,
        "reason": event.reason,
        "reason_label": _reason_label(event.reason),
        "old_price_retail": event.old_price_retail,
        "new_price_retail": event.new_price_retail,
        "old_price_final": event.old_price_final,
        "new_price_final": event.new_price_final,
        "old_profit": event.old_profit,
        "new_profit": event.new_profit,
        "target_profit": event.target_profit,
        "wb_discount": event.wb_discount,
        "old_discount": event.old_discount,
        "new_discount": event.new_discount,
        "price_delta": event.price_delta,
        "price_delta_percent": event.price_delta_percent,
        "created_at": _serialize_dt(event.created_at),
    }


def build_item_decision(item: models.Item) -> Dict[str, Any]:
    current_price_retail = float(item.wb_price_base or 0)
    current_price_final = float(item.wb_price_final or 0)
    current_discount = _normalize_discount(item.wb_discount)
    locked_discount = _locked_discount(item)
    locked_base_price = _locked_base_price(item)
    target_base_price = int(round(locked_base_price))
    target_final_from_base = unit_economics.final_price_from_base(target_base_price, locked_discount)
    locked_final_price = target_final_from_base
    tolerance = float(item.price_tolerance_rub or 50)
    price_drift = current_price_final - target_final_from_base
    base_price_drift = current_price_retail - target_base_price
    abs_drift = abs(price_drift)
    discount_delta = locked_discount - current_discount

    current_profit = _current_profit(item, current_price_final)
    min_profit = float(item.min_profit_rub or 0)
    desired_profit = float(item.desired_profit_rub or item.target_profit or 0)
    recommendation = unit_economics.build_price_recommendation(
        locked_final_price=locked_final_price,
        locked_discount=locked_discount,
        current_profit_per_unit=current_profit,
        min_profit_rub=min_profit,
        desired_profit_rub=desired_profit,
        cost_price=float(item.cost_price or 0),
        logistics=float(item.logistics_cost or 0),
        tax_rate=float(item.tax_rate or 0),
        commission=float(item.wb_commission or 0),
        return_cost_per_unit=float(item.return_cost_per_unit or 0),
        ads_cost_per_unit=float(item.ads_cost_per_unit or 0),
        overhead_per_unit=float(item.overhead_per_unit or 0),
        max_final_price=float(item.max_price or 0),
    )

    issues: List[str] = []
    if not item.is_active:
        issues.append("inactive")
    if not item.price_lock_enabled:
        issues.append("price_lock_disabled")
    if locked_base_price <= 0:
        issues.append("missing_locked_price")
    if current_price_retail <= 0 or current_price_final <= 0:
        issues.append("missing_live_price")
    if not _discount_is_valid(locked_discount):
        issues.append("invalid_locked_discount")

    should_auto_update = False
    reason_code = "within_tolerance"
    if issues:
        reason_code = issues[0]
    elif abs_drift > tolerance or discount_delta != 0:
        should_auto_update = True
        reason_code = "price_lock_drift"

    needs_manual_action = recommendation["reason_code"] in {
        "profit_below_minimum",
        "profit_below_desired",
        "economics_above_price_ceiling",
    }

    auto_ready = not issues
    status = "OK"
    if issues:
        status = "SETUP"
    elif should_auto_update:
        status = "PRICE_DRIFT"
    elif needs_manual_action:
        status = "REVIEW"

    return {
        "nm_id": item.nm_id,
        "name": item.name,
        "photo_url": item.photo_url,
        "mode": "price_lock" if item.price_lock_enabled else "manual",
        "repricer_mode": item.repricer_mode,
        "pricing_strategy": item.pricing_strategy or PRICE_LOCK_STRATEGY,
        "is_active": item.is_active,
        "price_lock_enabled": bool(item.price_lock_enabled),
        "auto_ready": auto_ready,
        "should_auto_update": should_auto_update,
        "needs_manual_action": needs_manual_action,
        "reason_code": reason_code,
        "reason_label": _reason_label(reason_code),
        "wb_discount": current_discount,
        "locked_discount": locked_discount,
        "target_discount": locked_discount,
        "recommended_discount": locked_discount,
        "discount_delta": discount_delta,
        "current_price_retail": current_price_retail,
        "current_price": current_price_final,
        "locked_price_base": target_base_price,
        "locked_final_price": locked_final_price,
        "target_final_price": locked_final_price,
        "target_base_price": target_base_price,
        "target_final_from_base": target_final_from_base,
        "price_tolerance_rub": tolerance,
        "price_drift": round(price_drift, 0),
        "base_price_drift": round(base_price_drift, 0),
        "current_profit": round(current_profit, 0),
        "target_profit": desired_profit,
        "desired_profit_rub": desired_profit,
        "min_profit_rub": min_profit,
        "profit_gap": round(min_profit - current_profit, 0),
        "recommended_price_final": round(float(recommendation["recommended_final_price"]), 0),
        "recommended_price_retail": round(float(recommendation["recommended_base_price"]), 0),
        "projected_profit": round(float(recommendation["projected_profit_per_unit"]), 0),
        "price_delta": round(target_base_price - current_price_retail, 0),
        "price_delta_pct": round(((target_base_price - current_price_retail) / current_price_retail * 100), 2) if current_price_retail else 0,
        "final_price_delta": round(target_final_from_base - current_price_final, 0),
        "final_price_delta_pct": round(((target_final_from_base - current_price_final) / current_price_final * 100), 2) if current_price_final else 0,
        "min_price": float(item.min_price or 0),
        "max_price": float(item.max_price or 0),
        "min_viable_price": round(float(recommendation["min_viable_price"]), 0),
        "recommendation_reason_code": recommendation["reason_code"],
        "recommendation_reason_text": recommendation["reason_text"],
        "recommendation_severity": recommendation["severity"],
        "ceiling_applied": recommendation["reason_code"] == "economics_above_price_ceiling",
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
        raise RuntimeError("WB не вернул актуальные цены.")

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

        if not item.locked_final_price:
            item.locked_final_price = item.wb_price_base
        if item.locked_discount is None:
            item.locked_discount = item.wb_discount
        if item.target_discount is None:
            item.target_discount = item.locked_discount

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
            -abs(float(row.get("price_drift") or 0)),
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
        new_discount = update.get("new_discount")
        if new_discount is not None and not _discount_is_valid(new_discount):
            continue
        normalized_updates.append(
            {
                "nm_id": nm_id,
                "new_price": new_price,
                "new_discount": new_discount,
                "reason": update.get("reason", default_reason),
            }
        )

    if not normalized_updates:
        return []

    result = await db.execute(select(models.Item).filter(models.Item.nm_id.in_([u["nm_id"] for u in normalized_updates])))
    items_by_nm_id = {item.nm_id: item for item in result.scalars().all()}

    planned_changes: List[Dict[str, Any]] = []
    for update in normalized_updates:
        item = items_by_nm_id.get(update["nm_id"])
        if not item:
            continue

        old_price_retail = float(item.wb_price_base or 0)
        old_price_final = float(item.wb_price_final or 0)
        old_discount = _normalize_discount(item.wb_discount)
        new_price_retail = int(update["new_price"])
        new_discount = _normalize_discount(update.get("new_discount") if update.get("new_discount") is not None else _locked_discount(item))
        if int(old_price_retail) == new_price_retail and old_discount == new_discount:
            continue

        new_price_final = unit_economics.final_price_from_base(new_price_retail, new_discount)
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
                "target_profit": float(item.desired_profit_rub or item.target_profit or 0),
                "wb_discount": new_discount,
                "old_discount": old_discount,
                "new_discount": new_discount,
                "price_delta": price_delta,
                "price_delta_percent": price_delta_percent,
                "reason": update["reason"],
            }
        )

    if not planned_changes:
        return []

    wb_payload = [
        {"nmID": change["nm_id"], "price": int(change["new_price_retail"]), "discount": int(change["new_discount"])}
        for change in planned_changes
    ]
    upload_response = wb.update_prices(wb_payload)
    if not upload_response or upload_response is False or (isinstance(upload_response, dict) and not upload_response.get("accepted", True)):
        raise RuntimeError("WB не принял пакет обновления цен.")

    upload_task = models.WbPriceUploadTask(
        upload_id=str(upload_response.get("upload_id")) if isinstance(upload_response, dict) and upload_response.get("upload_id") else None,
        source=source,
        status="created",
        payload_json=wb_payload,
        response_json=upload_response if isinstance(upload_response, dict) else {"accepted": True},
    )
    db.add(upload_task)

    persisted_changes: List[Dict[str, Any]] = []
    for change in planned_changes:
        item = change.pop("item")
        item.wb_price_base = change["new_price_retail"]
        item.wb_discount = change["new_discount"]
        item.wb_price_final = change["new_price_final"]
        item.locked_discount = change["new_discount"]
        item.target_discount = change["new_discount"]
        item.updated_at = _now_utc()

        db.add(
            models.PriceHistory(
                nm_id=item.nm_id,
                price_retail=change["new_price_retail"],
                discount=change["wb_discount"],
                final_price=change["new_price_final"],
                source=source,
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
                old_discount=change["old_discount"],
                new_discount=change["new_discount"],
                price_delta=change["price_delta"],
                price_delta_percent=change["price_delta_percent"],
            )
        )
        persisted_changes.append(change)

    return persisted_changes


async def run_background_repricing(db: AsyncSession, source: str = "scheduler_price_lock") -> Dict[str, Any]:
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
                "new_price": int(row["target_base_price"]),
                "new_discount": int(row["locked_discount"]),
                "reason": "price_lock_drift",
            }
            for row in report
            if row["should_auto_update"]
        ]
        manual_candidates = [row for row in report if row["needs_manual_action"]]
        auto_ready_items = [row for row in report if row["auto_ready"]]
        skipped_items = [row for row in report if not row["should_auto_update"]]

        changes = await apply_price_updates(
            db,
            auto_updates,
            source=source,
            default_reason="price_lock_drift",
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


async def get_recent_events(db: AsyncSession, *, limit: int = 20, source: str | None = None) -> List[Dict[str, Any]]:
    query = select(models.RepricerEvent).order_by(models.RepricerEvent.created_at.desc(), models.RepricerEvent.id.desc())
    if source:
        query = query.filter(models.RepricerEvent.source == source)

    result = await db.execute(query.limit(limit))
    events = result.scalars().all()
    return [_serialize_event(event) for event in events]


async def get_automation_status(db: AsyncSession) -> Dict[str, Any]:
    run_result = await db.execute(
        select(models.RepricerRun).order_by(models.RepricerRun.started_at.desc(), models.RepricerRun.id.desc()).limit(1)
    )
    last_run = run_result.scalars().first()

    report = await build_repricer_report(db, active_only=True)
    locked_items = [row for row in report if row["price_lock_enabled"]]
    auto_ready_items = [row for row in report if row["auto_ready"]]
    pending_auto_items = [row for row in report if row["should_auto_update"]]
    manual_review_items = [row for row in report if row["needs_manual_action"]]

    return {
        "strategy": PRICE_LOCK_STRATEGY,
        "strategy_label": PRICE_LOCK_STRATEGY_LABEL,
        "strategy_description": PRICE_LOCK_STRATEGY_DESCRIPTION,
        "schedule_interval_minutes": 60,
        "active_items": len(report),
        "locked_items": len(locked_items),
        "auto_mode_items": len(locked_items),
        "auto_ready_items": len(auto_ready_items),
        "pending_auto_items": len(pending_auto_items),
        "manual_review_items": len(manual_review_items),
        "last_run": _serialize_run(last_run),
        "recent_changes": await get_recent_events(db, limit=5, source="scheduler_price_lock"),
    }
