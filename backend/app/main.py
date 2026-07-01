from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import database, models, schemas, wb_client
from .services import notifier, repricer, unit_economics
from app.services.scheduler import check_prices_job, sync_finance_job, sync_items_job

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("📦 Инициализация БД...")
    await database.init_db()

    print("🟢 Запуск планировщика задач...")
    scheduler.add_job(check_prices_job, "interval", minutes=60)
    scheduler.add_job(sync_items_job, "interval", hours=6)
    scheduler.add_job(sync_finance_job, CronTrigger(hour=3, minute=0))
    scheduler.start()

    yield

    print("🔴 Остановка планировщика...")
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)


@app.on_event("startup")
async def startup():
    async with database.engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def pick(row: Dict[str, Any], *keys: str, default=None):
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return default


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y", "%d.%m.%Y %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def normalize_dt(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def record_operation_date(record: models.FinanceRecord) -> Optional[datetime]:
    return normalize_dt(record.sale_dt or record.order_dt or record.rr_dt or record.date_from)


def is_sale_operation(oper_type: str | None) -> bool:
    value = (oper_type or "").lower()
    return "продаж" in value or "sale" in value


def is_return_operation(oper_type: str | None) -> bool:
    value = (oper_type or "").lower()
    return "возврат" in value or "return" in value


async def upsert_items_payload(items: List[schemas.ItemCreate], db: AsyncSession) -> Tuple[int, int, List[models.Item]]:
    created = 0
    updated = 0
    persisted: List[models.Item] = []

    for item in items:
        result = await db.execute(select(models.Item).filter(models.Item.nm_id == item.nm_id))
        db_item = result.scalars().first()

        payload = item.model_dump(exclude_unset=True)
        if db_item:
            for key, value in payload.items():
                setattr(db_item, key, value)
            updated += 1
        else:
            db_item = models.Item(**payload)
            db.add(db_item)
            created += 1

        if db_item.desired_profit_rub in (None, 0) and db_item.target_profit:
            db_item.desired_profit_rub = db_item.target_profit
        if db_item.locked_discount is None:
            db_item.locked_discount = db_item.target_discount if db_item.target_discount is not None else db_item.wb_discount
        if not db_item.locked_final_price and db_item.wb_price_base:
            db_item.locked_final_price = db_item.wb_price_base

        persisted.append(db_item)

    return created, updated, persisted


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


@app.post("/items/import_from_wb")
async def import_items_from_wb(db: AsyncSession = Depends(database.get_db)):
    cards = wb_client.wb.get_cards()
    prices_map = wb_client.wb.get_prices()

    if not cards:
        return {"status": "error", "message": "Не удалось получить список товаров"}

    count_new = 0
    count_updated = 0

    for card in cards:
        result = await db.execute(select(models.Item).filter(models.Item.nm_id == card["nm_id"]))
        db_item = result.scalars().first()
        price_info = prices_map.get(card["nm_id"], {"wb_price_base": 0, "wb_discount": 0, "wb_price_final": 0})

        if db_item:
            db_item.photo_url = card["photo_url"]
            db_item.vendor_code = card["vendor_code"]
            db_item.name = card["name"]
            db_item.wb_price_base = price_info["wb_price_base"]
            db_item.wb_discount = price_info["wb_discount"]
            db_item.wb_price_final = price_info["wb_price_final"]
            if not db_item.locked_final_price:
                db_item.locked_final_price = db_item.wb_price_base
            if db_item.locked_discount is None:
                db_item.locked_discount = db_item.wb_discount
            if db_item.target_discount is None:
                db_item.target_discount = db_item.locked_discount
            count_updated += 1
        else:
            new_item = models.Item(
                nm_id=card["nm_id"],
                vendor_code=card["vendor_code"],
                name=card["name"],
                photo_url=card["photo_url"],
                wb_price_base=price_info["wb_price_base"],
                wb_discount=price_info["wb_discount"],
                wb_price_final=price_info["wb_price_final"],
                target_discount=price_info["wb_discount"],
                locked_discount=price_info["wb_discount"],
                locked_final_price=price_info["wb_price_base"],
                price_lock_enabled=True,
                pricing_strategy="fixed_final_price",
                price_tolerance_rub=50,
                cost_price=0,
                target_profit=0,
                desired_profit_rub=0,
                min_profit_rub=0,
            )
            db.add(new_item)
            count_new += 1

    await db.commit()
    return {"status": "success", "new": count_new, "updated": count_updated}


@app.get("/items/", response_model=List[schemas.Item])
async def read_items(db: AsyncSession = Depends(database.get_db)):
    result = await db.execute(select(models.Item).order_by(models.Item.nm_id))
    return result.scalars().all()


@app.post("/items/", response_model=schemas.Item)
async def create_or_update_item(item: schemas.ItemCreate, db: AsyncSession = Depends(database.get_db)):
    _, _, persisted = await upsert_items_payload([item], db)
    db_item = persisted[0]
    await db.commit()
    await db.refresh(db_item)
    return db_item


@app.post("/items/bulk_upsert", response_model=schemas.BulkItemsUpsertResult)
async def bulk_upsert_items(items: List[schemas.ItemCreate], db: AsyncSession = Depends(database.get_db)):
    if not items:
        return schemas.BulkItemsUpsertResult(total=0, created=0, updated=0)

    created, updated, _ = await upsert_items_payload(items, db)
    await db.commit()
    return schemas.BulkItemsUpsertResult(total=len(items), created=created, updated=updated)


# ---------------------------------------------------------------------------
# Legacy order/sales sync
# ---------------------------------------------------------------------------


@app.post("/analytics/sync_stats")
async def sync_stats(req: schemas.SyncRequest, db: AsyncSession = Depends(database.get_db)):
    items_count = await db.execute(select(func.count(models.Item.nm_id)))
    if items_count.scalar() == 0:
        raise HTTPException(status_code=400, detail="База товаров пуста. Сначала синхронизируйте товары.")

    date_from = (datetime.now() - timedelta(days=req.days)).strftime("%Y-%m-%d")
    try:
        orders_data = wb_client.wb.get_orders(date_from)
        sales_data = wb_client.wb.get_sales(date_from)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    new_orders = 0
    for order_row in orders_data or []:
        item_exists = await db.execute(select(models.Item).filter(models.Item.nm_id == order_row.get("nmId")))
        if not item_exists.scalars().first():
            continue
        result = await db.execute(select(models.Order).filter(models.Order.srid == order_row.get("srid")))
        if not result.scalars().first():
            db.add(
                models.Order(
                    srid=order_row.get("srid"),
                    nm_id=order_row.get("nmId"),
                    total_price=order_row.get("totalPrice"),
                    warehouse_name=order_row.get("warehouseName"),
                    oblast_okrug_name=order_row.get("oblastOkrugName"),
                    income_id=order_row.get("incomeID"),
                    is_cancel=order_row.get("isCancel", False),
                    date=parse_dt(order_row.get("date")),
                )
            )
            new_orders += 1

    new_sales = 0
    for sale_row in sales_data or []:
        item_exists = await db.execute(select(models.Item).filter(models.Item.nm_id == sale_row.get("nmId")))
        if not item_exists.scalars().first():
            continue
        result = await db.execute(select(models.Sale).filter(models.Sale.sale_id == sale_row.get("saleID")))
        if not result.scalars().first():
            db.add(
                models.Sale(
                    sale_id=sale_row.get("saleID"),
                    srid=sale_row.get("srid"),
                    nm_id=sale_row.get("nmId"),
                    price_with_disc=sale_row.get("priceWithDisc"),
                    for_pay=sale_row.get("forPay"),
                    finished_price=sale_row.get("finishedPrice"),
                    region_name=sale_row.get("regionName"),
                    date=parse_dt(sale_row.get("date")),
                )
            )
            new_sales += 1

    await db.commit()
    return {"status": "success", "new_orders": new_orders, "new_sales": new_sales, "date_from": date_from}


@app.get("/analytics/dashboard_data")
async def get_dashboard_data(db: AsyncSession = Depends(database.get_db)):
    q_orders = select(func.date_trunc("day", models.Order.date).label("day"), func.count(models.Order.srid)).group_by("day").order_by("day")
    q_sales = select(func.date_trunc("day", models.Sale.date).label("day"), func.count(models.Sale.sale_id)).group_by("day").order_by("day")
    res_orders = await db.execute(q_orders)
    res_sales = await db.execute(q_sales)
    orders_list = [{"date": row[0].strftime("%Y-%m-%d"), "count": row[1], "type": "Заказы"} for row in res_orders.all()]
    sales_list = [{"date": row[0].strftime("%Y-%m-%d"), "count": row[1], "type": "Продажи"} for row in res_sales.all()]
    return {"chart_data": orders_list + sales_list, "summary": {"total_orders": sum(x["count"] for x in orders_list), "total_sales": sum(x["count"] for x in sales_list)}}


# ---------------------------------------------------------------------------
# Finance import and analytics
# ---------------------------------------------------------------------------


def build_finance_record_from_row(row: Dict[str, Any]) -> Optional[models.FinanceRecord]:
    rrd_id = pick(row, "rrdId", "rrd_id")
    if not rrd_id:
        return None

    return models.FinanceRecord(
        rrd_id=to_int(rrd_id),
        report_id=to_int(pick(row, "realizationReportId", "realizationreport_id")),
        nm_id=to_int(pick(row, "nmId", "nm_id"), default=None),
        srid=pick(row, "srid"),
        vendor_code=pick(row, "saName", "sa_name", "vendorCode"),
        barcode=pick(row, "barcode"),
        subject_name=pick(row, "subjectName", "subject_name"),
        brand_name=pick(row, "brandName", "brand_name"),
        date_from=parse_dt(pick(row, "dateFrom", "date_from")),
        date_to=parse_dt(pick(row, "dateTo", "date_to")),
        order_dt=parse_dt(pick(row, "orderDt", "order_dt")),
        sale_dt=parse_dt(pick(row, "saleDt", "sale_dt")),
        rr_dt=parse_dt(pick(row, "rrDt", "rr_dt")),
        oper_type=pick(row, "supplierOperName", "supplier_oper_name"),
        doc_type_name=pick(row, "docTypeName", "doc_type_name"),
        quantity=to_float(pick(row, "quantity"), 1.0),
        retail_price=to_float(pick(row, "retailPrice", "retail_price")),
        retail_amount=to_float(pick(row, "retailAmount", "retail_amount")),
        retail_price_withdisc_rub=to_float(pick(row, "retailPriceWithdiscRub", "retail_price_withdisc_rub")),
        amount=to_float(pick(row, "forPay", "ppvzForPay", "ppvz_for_pay")),
        commission_percent=to_float(pick(row, "commissionPercent", "commission_percent")),
        ppvz_sales_commission=to_float(pick(row, "ppvzSalesCommission", "ppvz_sales_commission")),
        ppvz_reward=to_float(pick(row, "ppvzReward", "ppvz_reward")),
        acquiring_fee=to_float(pick(row, "acquiringFee", "acquiring_fee")),
        acquiring_percent=to_float(pick(row, "acquiringPercent", "acquiring_percent")),
        delivery_amount=to_float(pick(row, "deliveryAmount", "delivery_amount")),
        return_amount=to_float(pick(row, "returnAmount", "return_amount")),
        delivery_rub=to_float(pick(row, "deliveryRub", "delivery_rub", "deliveryService", "delivery_service")),
        delivery_service=to_float(pick(row, "deliveryService", "delivery_service", "deliveryRub", "delivery_rub")),
        rebill_logistic_cost=to_float(pick(row, "rebillLogisticCost", "rebill_logistic_cost")),
        storage_fee=to_float(pick(row, "storageFee", "paidStorage", "storage_fee")),
        deduction=to_float(pick(row, "deduction")),
        acceptance=to_float(pick(row, "acceptance", "paidAcceptance", "paid_acceptance")),
        penalty=to_float(pick(row, "penalty")),
        additional_payment=to_float(pick(row, "additionalPayment", "additional_payment")),
        supplier_promo=to_float(pick(row, "supplierPromo", "supplier_promo")),
        product_discount_for_report=to_float(pick(row, "productDiscountForReport", "product_discount_for_report")),
        seller_promo_discount=to_float(pick(row, "sellerPromoDiscount", "seller_promo_discount")),
        loyalty_discount=to_float(pick(row, "loyaltyDiscount", "loyalty_discount")),
        cashback_amount=to_float(pick(row, "cashbackAmount", "cashback_amount")),
        cashback_discount=to_float(pick(row, "cashbackDiscount", "cashback_discount")),
        wibes_wb_discount_percent=to_float(pick(row, "wibesWbDiscountPercent", "wibes_wb_discount_percent")),
        sale_price_promocode_discount_prc=to_float(pick(row, "salePricePromocodeDiscountPrc", "sale_price_promocode_discount_prc")),
        sale_price_wholesale_discount_prc=to_float(pick(row, "salePriceWholesaleDiscountPrc", "sale_price_wholesale_discount_prc")),
        warehouse_name=pick(row, "warehouseName", "warehouse_name", "officeName", "office_name"),
        office_name=pick(row, "officeName", "office_name"),
        site_country=pick(row, "siteCountry", "site_country"),
        delivery_method=pick(row, "deliveryMethod", "delivery_method"),
        raw_json=row,
    )


@app.post("/analytics/sync_finance")
async def sync_finance(req: schemas.SyncRequest, db: AsyncSession = Depends(database.get_db)):
    date_to_dt = datetime.now(timezone.utc)
    sync_days = max(1, min(req.days or 3650, 3650))
    date_from_dt = date_to_dt - timedelta(days=sync_days)
    date_from = date_from_dt.strftime("%Y-%m-%d")
    date_to = date_to_dt.strftime("%Y-%m-%d")

    try:
        report_data = wb_client.wb.get_financial_report(date_from, date_to)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not report_data:
        return {"status": "warning", "message": "Данных нет", "new_records": 0, "total_found": 0}

    new_records = 0
    raw_rows = 0
    for row in report_data:
        record = build_finance_record_from_row(row)
        if not record:
            continue

        db.add(
            models.FinanceRawRow(
                source_api_version="finance_v1_or_legacy",
                report_id=record.report_id,
                rrd_id=record.rrd_id,
                nm_id=record.nm_id,
                srid=record.srid,
                raw_json=row,
            )
        )
        raw_rows += 1

        existing = await db.execute(select(models.FinanceRecord).filter(models.FinanceRecord.rrd_id == record.rrd_id))
        if existing.scalars().first():
            continue

        db.add(record)
        new_records += 1

    await db.commit()
    return {"status": "success", "new_records": new_records, "raw_rows": raw_rows, "total_found": len(report_data), "date_from": date_from, "date_to": date_to}


async def get_finance_records(db: AsyncSession, days: int = 30) -> Tuple[List[models.FinanceRecord], Dict[int, models.Item]]:
    result = await db.execute(select(models.FinanceRecord))
    rows = result.scalars().all()
    safe_days = max(0, min(days or 0, 3650))
    if safe_days == 0:
        filtered = rows
    else:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=safe_days)
        # Для ограниченных периодов строки без даты не включаем: иначе 7/14/30 дней
        # визуально дают одинаковый результат и фильтр кажется нерабочим.
        filtered = [row for row in rows if (record_operation_date(row) is not None and record_operation_date(row) >= cutoff)]

    item_result = await db.execute(select(models.Item))
    items = {item.nm_id: item for item in item_result.scalars().all()}
    return filtered, items


def compute_analytics(rows: List[models.FinanceRecord], items: Dict[int, models.Item]) -> Dict[str, Any]:
    unit: Dict[int, Dict[str, Any]] = {}
    daily: Dict[str, Dict[str, float]] = {}

    summary = {
        "gross_revenue": 0.0,
        "for_pay": 0.0,
        "sales_qty": 0.0,
        "returns_qty": 0.0,
        "logistics": 0.0,
        "storage": 0.0,
        "deductions": 0.0,
        "acceptance": 0.0,
        "penalties": 0.0,
        "additional_payment": 0.0,
        "acquiring": 0.0,
        "cogs": 0.0,
        "ads": 0.0,
        "overhead": 0.0,
        "tax": 0.0,
        "net_profit": 0.0,
        "wb_commission": 0.0,
    }

    for row in rows:
        nm_id = row.nm_id or 0
        item = items.get(nm_id)
        item_name = item.name if item else str(nm_id or "—")
        quantity = abs(float(row.quantity or 1)) or 1
        sale = is_sale_operation(row.oper_type)
        ret = is_return_operation(row.oper_type)

        if nm_id not in unit:
            unit[nm_id] = {
                "nm_id": nm_id,
                "item_name": item_name,
                "locked_price": float(item.locked_final_price or item.wb_price_final or 0) if item else 0.0,
                "current_price": float(item.wb_price_final or 0) if item else 0.0,
                "recommended_price": float(item.locked_final_price or item.wb_price_final or 0) if item else 0.0,
                "min_viable_price": 0.0,
                "sales_qty": 0.0,
                "returns_qty": 0.0,
                "return_rate_pct": 0.0,
                "retail_amount": 0.0,
                "for_pay": 0.0,
                "wb_commission": 0.0,
                "logistics": 0.0,
                "storage": 0.0,
                "penalties": 0.0,
                "deductions": 0.0,
                "acceptance": 0.0,
                "acquiring": 0.0,
                "cogs": 0.0,
                "ads": 0.0,
                "overhead": 0.0,
                "tax": 0.0,
                "profit": 0.0,
                "profit_per_unit": 0.0,
                "status": "no_data",
                "recommendation": "Недостаточно данных",
            }

        bucket = unit[nm_id]
        expenses = (
            float(row.delivery_rub or 0)
            + float(row.delivery_service or 0)
            + float(row.rebill_logistic_cost or 0)
            + float(row.storage_fee or 0)
            + float(row.deduction or 0)
            + float(row.acceptance or 0)
            + float(row.penalty or 0)
            + float(row.acquiring_fee or 0)
        )
        logistics = float(row.delivery_rub or row.delivery_service or 0) + float(row.rebill_logistic_cost or 0)
        commission = float(row.ppvz_sales_commission or 0)
        if not commission and float(row.retail_amount or 0) > 0 and float(row.amount or 0) > 0:
            commission = max(0.0, float(row.retail_amount or 0) - float(row.amount or 0))

        sales_qty = quantity if sale else 0.0
        returns_qty = quantity if ret else 0.0
        cogs = (float(item.cost_price or 0) * sales_qty) if item else 0.0
        ads = (float(item.ads_cost_per_unit or 0) * sales_qty) if item else 0.0
        overhead = (float(item.overhead_per_unit or 0) * sales_qty) if item else 0.0
        tax = (float(row.retail_amount or 0) * float(item.tax_rate or 0)) if item and sale else 0.0
        profit = float(row.amount or 0) - cogs - expenses + float(row.additional_payment or 0) - ads - overhead - tax

        bucket["sales_qty"] += sales_qty
        bucket["returns_qty"] += returns_qty
        bucket["retail_amount"] += float(row.retail_amount or 0)
        bucket["for_pay"] += float(row.amount or 0)
        bucket["wb_commission"] += commission
        bucket["logistics"] += logistics
        bucket["storage"] += float(row.storage_fee or 0)
        bucket["penalties"] += float(row.penalty or 0)
        bucket["deductions"] += float(row.deduction or 0)
        bucket["acceptance"] += float(row.acceptance or 0)
        bucket["acquiring"] += float(row.acquiring_fee or 0)
        bucket["cogs"] += cogs
        bucket["ads"] += ads
        bucket["overhead"] += overhead
        bucket["tax"] += tax
        bucket["profit"] += profit

        for key in summary:
            if key in bucket:
                continue
        summary["gross_revenue"] += float(row.retail_amount or 0)
        summary["for_pay"] += float(row.amount or 0)
        summary["sales_qty"] += sales_qty
        summary["returns_qty"] += returns_qty
        summary["logistics"] += logistics
        summary["storage"] += float(row.storage_fee or 0)
        summary["deductions"] += float(row.deduction or 0)
        summary["acceptance"] += float(row.acceptance or 0)
        summary["penalties"] += float(row.penalty or 0)
        summary["additional_payment"] += float(row.additional_payment or 0)
        summary["acquiring"] += float(row.acquiring_fee or 0)
        summary["cogs"] += cogs
        summary["ads"] += ads
        summary["overhead"] += overhead
        summary["tax"] += tax
        summary["net_profit"] += profit
        summary["wb_commission"] += commission

        op_date = record_operation_date(row)
        day_key = op_date.strftime("%Y-%m-%d") if op_date else "Без даты"
        if day_key not in daily:
            daily[day_key] = {"date": day_key, "revenue": 0.0, "profit": 0.0, "logistics": 0.0, "sales_qty": 0.0, "returns_qty": 0.0}
        daily[day_key]["revenue"] += float(row.retail_amount or 0)
        daily[day_key]["profit"] += profit
        daily[day_key]["logistics"] += logistics
        daily[day_key]["sales_qty"] += sales_qty
        daily[day_key]["returns_qty"] += returns_qty

    recommendations = []
    for nm_id, bucket in unit.items():
        item = items.get(nm_id)
        sales_qty = bucket["sales_qty"]
        total_order_like_qty = bucket["sales_qty"] + bucket["returns_qty"]
        bucket["return_rate_pct"] = (bucket["returns_qty"] / total_order_like_qty * 100) if total_order_like_qty else 0.0
        bucket["profit_per_unit"] = (bucket["profit"] / sales_qty) if sales_qty else 0.0
        if item:
            locked_base_price = float(item.locked_final_price or item.wb_price_base or 0)
            locked_discount = int(item.locked_discount if item.locked_discount is not None else item.wb_discount or 0)
            locked_price = unit_economics.final_price_from_base(locked_base_price, locked_discount)
            actual_logistics = (bucket["logistics"] / sales_qty) if sales_qty else float(item.logistics_cost or 0)
            rec = unit_economics.build_price_recommendation(
                locked_final_price=locked_price,
                locked_discount=locked_discount,
                current_profit_per_unit=bucket["profit_per_unit"],
                min_profit_rub=float(item.min_profit_rub or 0),
                desired_profit_rub=float(item.desired_profit_rub or item.target_profit or 0),
                cost_price=float(item.cost_price or 0),
                logistics=actual_logistics,
                tax_rate=float(item.tax_rate or 0),
                commission=float(item.wb_commission or 0),
                return_cost_per_unit=float(item.return_cost_per_unit or 0),
                ads_cost_per_unit=float(item.ads_cost_per_unit or 0),
                overhead_per_unit=float(item.overhead_per_unit or 0),
                max_final_price=float(item.max_price or 0),
            )
            bucket["recommended_price"] = rec["recommended_final_price"]
            bucket["min_viable_price"] = rec["min_viable_price"]
            bucket["recommendation"] = rec["reason_text"]
            bucket["status"] = rec["severity"]
            recommendations.append(
                {
                    "nm_id": nm_id,
                    "name": item.name,
                    "current_final_price": float(item.wb_price_final or 0),
                    "locked_price_base": locked_base_price,
                    "locked_final_price": locked_price,
                    "recommended_final_price": rec["recommended_final_price"],
                    "recommended_base_price": rec["recommended_base_price"],
                    "recommended_discount": rec["recommended_discount"],
                    "current_profit_per_unit": bucket["profit_per_unit"],
                    "projected_profit_per_unit": rec["projected_profit_per_unit"],
                    "min_viable_price": rec["min_viable_price"],
                    "reason_code": rec["reason_code"],
                    "reason_text": rec["reason_text"],
                    "severity": rec["severity"],
                    "confidence": "low" if sales_qty < 3 else "medium",
                }
            )

    margin = (summary["net_profit"] / summary["gross_revenue"] * 100) if summary["gross_revenue"] else 0.0
    summary["margin_pct"] = margin
    summary["avg_profit_per_unit"] = summary["net_profit"] / summary["sales_qty"] if summary["sales_qty"] else 0.0
    summary["return_rate_pct"] = summary["returns_qty"] / (summary["sales_qty"] + summary["returns_qty"]) * 100 if (summary["sales_qty"] + summary["returns_qty"]) else 0.0

    pnl = [
        {"name": "Выручка", "value": summary["gross_revenue"]},
        {"name": "Комиссия WB", "value": -summary["wb_commission"]},
        {"name": "Эквайринг", "value": -summary["acquiring"]},
        {"name": "Себестоимость", "value": -summary["cogs"]},
        {"name": "Логистика", "value": -summary["logistics"]},
        {"name": "Хранение/приёмка/удержания", "value": -(summary["storage"] + summary["acceptance"] + summary["deductions"])},
        {"name": "Штрафы", "value": -summary["penalties"]},
        {"name": "Доплаты", "value": summary["additional_payment"]},
        {"name": "Реклама и накладные", "value": -(summary["ads"] + summary["overhead"])},
        {"name": "Налог", "value": -summary["tax"]},
        {"name": "Прибыль", "value": summary["net_profit"]},
    ]

    return {
        "summary": summary,
        "pnl": pnl,
        "timeseries": [daily[key] for key in sorted(daily.keys())],
        "unit_economics": sorted(unit.values(), key=lambda item: item["profit"], reverse=True),
        "recommendations": sorted(recommendations, key=lambda item: (item["severity"] != "critical", item["severity"] != "warning", item["nm_id"])),
    }


@app.get("/analytics/finance_dashboard")
async def get_finance_dashboard(db: AsyncSession = Depends(database.get_db)):
    rows, items = await get_finance_records(db, days=3650)
    analytics = compute_analytics(rows, items)
    return {
        "sales_count": analytics["summary"]["sales_qty"],
        "sales_sum": analytics["summary"]["for_pay"],
        "logistics_sum": analytics["summary"]["logistics"],
        "records": [
            {
                "date": record_operation_date(row),
                "type": row.oper_type,
                "item": row.nm_id,
                "amount": row.amount,
                "retail_amount": row.retail_amount,
                "logistics": row.delivery_rub or row.delivery_service,
                "penalty": row.penalty,
                "storage_fee": row.storage_fee,
                "deduction": row.deduction,
                "acceptance": row.acceptance,
                "acquiring_fee": row.acquiring_fee,
                "commission_percent": row.commission_percent,
            }
            for row in rows
        ],
        **analytics,
    }


@app.get("/analytics/summary")
async def analytics_summary(days: int = Query(30, ge=0, le=3650), db: AsyncSession = Depends(database.get_db)):
    rows, items = await get_finance_records(db, days=days)
    return compute_analytics(rows, items)["summary"]


@app.get("/analytics/unit-economics")
async def analytics_unit_economics(days: int = Query(30, ge=0, le=3650), db: AsyncSession = Depends(database.get_db)):
    rows, items = await get_finance_records(db, days=days)
    return {"items": compute_analytics(rows, items)["unit_economics"]}


@app.get("/analytics/timeseries")
async def analytics_timeseries(days: int = Query(30, ge=0, le=3650), db: AsyncSession = Depends(database.get_db)):
    rows, items = await get_finance_records(db, days=days)
    return {"points": compute_analytics(rows, items)["timeseries"]}


@app.get("/analytics/pnl")
async def analytics_pnl(days: int = Query(30, ge=0, le=3650), db: AsyncSession = Depends(database.get_db)):
    rows, items = await get_finance_records(db, days=days)
    return {"items": compute_analytics(rows, items)["pnl"]}


@app.get("/recommendations")
async def get_recommendations(days: int = Query(30, ge=0, le=3650), db: AsyncSession = Depends(database.get_db)):
    rows, items = await get_finance_records(db, days=days)
    return {"recommendations": compute_analytics(rows, items)["recommendations"]}


# ---------------------------------------------------------------------------
# Price lock / recommendations
# ---------------------------------------------------------------------------


@app.get("/repricer/status")
async def get_repricer_status(db: AsyncSession = Depends(database.get_db)):
    return await repricer.build_repricer_report(db, active_only=True)


@app.get("/repricer/automation_status")
async def get_repricer_automation_status(db: AsyncSession = Depends(database.get_db)):
    return await repricer.get_automation_status(db)


@app.get("/repricer/history")
async def get_repricer_history(limit: int = 20, db: AsyncSession = Depends(database.get_db)):
    safe_limit = max(1, min(limit, 100))
    return {"events": await repricer.get_recent_events(db, limit=safe_limit)}


@app.post("/repricer/run_auto_now")
async def run_auto_now(db: AsyncSession = Depends(database.get_db)):
    try:
        result = await repricer.run_background_repricing(db, source="manual_trigger")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    manual_alerts_batch = [
        {
            "name": item["name"] or str(item["nm_id"]),
            "profit": int(item["current_profit"]),
            "target": int(item.get("min_profit_rub") or 0),
            "new_price": int(item["recommended_price_retail"]),
            "new_discount": int(item["recommended_discount"]),
            "nm_id": item["nm_id"],
        }
        for item in result["manual_alerts"]
    ]

    if manual_alerts_batch:
        await notifier.send_batch_alert(manual_alerts_batch)
    if result["changes"]:
        await notifier.send_auto_report(result)

    return result


@app.post("/repricer/batch_update")
async def batch_update_prices(items: List[schemas.PriceUpdateReq], source: str = "manual_ui", db: AsyncSession = Depends(database.get_db)):
    if not items:
        return {"status": "empty"}

    try:
        changes = await repricer.apply_price_updates(
            db,
            ({"nm_id": item.nm_id, "new_price": item.new_price, "new_discount": item.new_discount, "reason": "manual_apply"} for item in items),
            source=source,
            default_reason="manual_apply",
        )
        await db.commit()
    except RuntimeError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "success", "updated": len(changes), "changes": changes}
