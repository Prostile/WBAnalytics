from fastapi import FastAPI, Depends, HTTPException
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Tuple

from . import models, schemas, database, wb_client
from .services import notifier, repricer

# --- ИМПОРТЫ ДЛЯ SCHEDULER ---
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.services.scheduler import check_prices_job, sync_finance_job, sync_items_job

# Создаем планировщик
scheduler = AsyncIOScheduler()

# Оборачиваем старт приложения
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("📦 Инициализация БД...")
    await database.init_db()
    
    print("🟢 Запуск Планировщика Фоновых Задач...")
    
    # 1. Проверка цен: каждые 60 минут
    scheduler.add_job(check_prices_job, 'interval', minutes=60)
    
    # 2. Обновление карточек товаров: каждые 6 часов
    scheduler.add_job(sync_items_job, 'interval', hours=6)
    
    # 3. Ночная выгрузка финансов (V5): каждый день в 03:00 ночи
    # Используем cron для точного времени
    scheduler.add_job(sync_finance_job, CronTrigger(hour=3, minute=0))
    
    scheduler.start()
    
    yield
    
    print("🔴 Остановка Планировщика...")
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)


async def upsert_items_payload(
    items: List[schemas.ItemCreate],
    db: AsyncSession,
) -> Tuple[int, int, List[models.Item]]:
    created = 0
    updated = 0
    persisted: List[models.Item] = []

    for item in items:
        result = await db.execute(select(models.Item).filter(models.Item.nm_id == item.nm_id))
        db_item = result.scalars().first()

        if db_item:
            for key, value in item.model_dump(exclude_unset=True).items():
                setattr(db_item, key, value)
            updated += 1
        else:
            db_item = models.Item(**item.model_dump(exclude_unset=True))
            db.add(db_item)
            created += 1

        persisted.append(db_item)

    return created, updated, persisted

# 1. При старте создаем таблицы
@app.on_event("startup")
async def startup():
    async with database.engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)

# --- ЭНДПОИНТЫ ---

# 1. Импорт из WB
@app.post("/items/import_from_wb")
async def import_items_from_wb(db: AsyncSession = Depends(database.get_db)):
    # 1. Скачиваем карточки (Контент)
    cards = wb_client.wb.get_cards()
    # 2. Скачиваем цены (Финансы)
    prices_map = wb_client.wb.get_prices()
    
    if not cards:
        return {"status": "error", "message": "Не удалось получить список товаров"}
    
    count_new = 0
    count_updated = 0
    
    for card in cards:
        result = await db.execute(select(models.Item).filter(models.Item.nm_id == card["nm_id"]))
        db_item = result.scalars().first()
        
        # Ищем цену для этого товара в скачанном словаре
        price_info = prices_map.get(card["nm_id"], {"wb_price_base": 0, "wb_discount": 0, "wb_price_final": 0})
        
        if db_item:
            # Обновляем контент
            db_item.photo_url = card["photo_url"]
            db_item.vendor_code = card["vendor_code"]
            db_item.name = card["name"]
            
            # Обновляем цены
            db_item.wb_price_base = price_info["wb_price_base"]
            db_item.wb_discount = price_info["wb_discount"]
            db_item.wb_price_final = price_info["wb_price_final"]
            
            count_updated += 1
        else:
            # Создаем новый
            new_item = models.Item(
                nm_id=card["nm_id"],
                vendor_code=card["vendor_code"],
                name=card["name"],
                photo_url=card["photo_url"],
                
                # Цены
                wb_price_base=price_info["wb_price_base"],
                wb_discount=price_info["wb_discount"],
                wb_price_final=price_info["wb_price_final"],
                target_discount=price_info["wb_discount"],
                
                cost_price=0,
                target_profit=0
            )
            db.add(new_item)
            count_new += 1
    
    await db.commit()
    return {"status": "success", "new": count_new, "updated": count_updated}

# 2. Получить все товары (ВОТ ЭТОЙ ФУНКЦИИ НЕ ХВАТАЛО)
@app.get("/items/", response_model=List[schemas.Item])
async def read_items(db: AsyncSession = Depends(database.get_db)):
    result = await db.execute(select(models.Item).order_by(models.Item.nm_id))
    items = result.scalars().all()
    return items

# 3. Обновить/Создать вручную
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

@app.post("/analytics/sync_stats")
async def sync_stats(req: schemas.SyncRequest, db: AsyncSession = Depends(database.get_db)):
    # 1. СНАЧАЛА ПРОВЕРЯЕМ ТОВАРЫ
    # Если товаров нет, заказы не к чему привязать, и они не сохранятся
    items_count = await db.execute(select(func.count(models.Item.nm_id)))
    if items_count.scalar() == 0:
        raise HTTPException(status_code=400, detail="База товаров пуста! Сначала нажмите 'Синхронизировать Товары' во вкладке Цены.")

    # 2. Дата: Берем "сегодня минус X дней"
    # Важно: используем datetime.now() сервера. Если у вас сервер в 2026 году, 
    # а WB в 2025, данных не будет. 
    # Для надежности поставим хардкод на 2024 год, если данных будет 0.
    date_from = "2024-01-01" #(datetime.now() - timedelta(days=req.days)).strftime("%Y-%m-%d")
    print(f"НАЧАЛО СИНХРОНИЗАЦИИ. Период: {req.days} дней (с {date_from})")
    # Можно раскомментировать эту строку, если хотите принудительно качать с 2024 года:
    # date_from = "2024-01-01" 

    try:
        # Качаем с повторами (логика в wb_client)
        orders_data = wb_client.wb.get_orders(date_from)
        sales_data = wb_client.wb.get_sales(date_from)
        print(f"📦 API WB вернул: {len(orders_data)} заказов")
        print(f"💰 API WB вернул: {len(sales_data)} продаж")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    new_orders = 0
    # Сохраняем заказы
    if orders_data:
        for o in orders_data:
            # Проверяем, есть ли такой товар у нас, чтобы не было ошибки ForeignKey
            # (Опционально: можно пропускать "чужие" артикулы)
            item_exists = await db.execute(select(models.Item).filter(models.Item.nm_id == o.get("nmId")))
            if not item_exists.scalars().first():
                continue # Пропускаем заказ, если товара нет в базе

            result = await db.execute(select(models.Order).filter(models.Order.srid == o.get("srid")))
            if not result.scalars().first():
                order = models.Order(
                    srid=o.get("srid"),
                    nm_id=o.get("nmId"),
                    total_price=o.get("totalPrice"),
                    warehouse_name=o.get("warehouseName"),
                    oblast_okrug_name=o.get("oblastOkrugName"),
                    income_id=o.get("incomeID"),
                    is_cancel=o.get("isCancel", False),
                    date=datetime.fromisoformat(o.get("date"))
                )
                db.add(order)
                new_orders += 1

    new_sales = 0
    # Сохраняем продажи
    if sales_data:
        for s in sales_data:
            item_exists = await db.execute(select(models.Item).filter(models.Item.nm_id == s.get("nmId")))
            if not item_exists.scalars().first():
                continue 

            result = await db.execute(select(models.Sale).filter(models.Sale.sale_id == s.get("saleID")))
            if not result.scalars().first():
                sale = models.Sale(
                    sale_id=s.get("saleID"),
                    srid=s.get("srid"),
                    nm_id=s.get("nmId"),
                    price_with_disc=s.get("priceWithDisc"),
                    for_pay=s.get("forPay"),
                    finished_price=s.get("finishedPrice"),
                    region_name=s.get("regionName"),
                    date=datetime.fromisoformat(s.get("date"))
                )
                db.add(sale)
                new_sales += 1
            
    await db.commit()
    return {"status": "success", "new_orders": new_orders, "new_sales": new_sales, "date_from": date_from}

@app.get("/analytics/dashboard_data")
async def get_dashboard_data(db: AsyncSession = Depends(database.get_db)):
    """Отдает данные, сгруппированные по дням"""
    
    # SQL запрос: "Дай мне дату и количество заказов за этот день"
    # TRUNC('day', date) обрезает часы и минуты, оставляя только день
    q_orders = (
        select(func.date_trunc('day', models.Order.date).label('day'), func.count(models.Order.srid))
        .group_by('day')
        .order_by('day')
    )
    
    q_sales = (
        select(func.date_trunc('day', models.Sale.date).label('day'), func.count(models.Sale.sale_id))
        .group_by('day')
        .order_by('day')
    )
    
    res_orders = await db.execute(q_orders)
    res_sales = await db.execute(q_sales)
    
    # Превращаем в список словарей
    orders_list = [{"date": row[0].strftime("%Y-%m-%d"), "count": row[1], "type": "Заказы"} for row in res_orders.all()]
    sales_list = [{"date": row[0].strftime("%Y-%m-%d"), "count": row[1], "type": "Продажи"} for row in res_sales.all()]
    
    return {
        "chart_data": orders_list + sales_list, # Объединяем в один список для графика
        "summary": {
            "total_orders": sum(x['count'] for x in orders_list),
            "total_sales": sum(x['count'] for x in sales_list)
        }
    }

@app.post("/analytics/sync_finance")
async def sync_finance(req: schemas.SyncRequest, db: AsyncSession = Depends(database.get_db)):
    # Берем период пошире. Если пользователь просит 30 дней, 
    # для финансов лучше брать чуть больше, чтобы не рвать отчеты.
    # Но для теста возьмем с 2024 года, раз там есть данные.
    date_from = "2024-01-01"
    date_to = datetime.now().strftime("%Y-%m-%d")
    
    print(f"🚀 СТАРТ загрузки Финансов (V5) с {date_from}")

    try:
        report_data = wb_client.wb.get_financial_report(date_from, date_to)
        
        if not report_data:
             # Если вернулся None или пустой список
            print("⚠️ Финансовый отчет пуст или ошибка.")
            return {"status": "warning", "message": "Данных нет"}
            
        print(f"📥 Получено строк отчета: {len(report_data)}")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    new_records = 0
    
    for row in report_data:
        # У каждой строки в отчете есть rrd_id - это уникальный ключ
        rrd_id = row.get("rrd_id")
        if not rrd_id: continue # Пропускаем мусор
        
        # Проверяем, есть ли запись в базе
        existing = await db.execute(select(models.FinanceRecord).filter(models.FinanceRecord.rrd_id == rrd_id))
        if existing.scalars().first():
            continue
            
        # Парсим даты (они могут быть с точками или None)
        def parse_dt(dt_str):
            if not dt_str: return None
            try: return datetime.fromisoformat(dt_str)
            except: return None

        record = models.FinanceRecord(
            rrd_id=rrd_id,
            report_id=row.get("realizationreport_id"),
            nm_id=row.get("nm_id"),
            
            date_from=parse_dt(row.get("date_from")),
            date_to=parse_dt(row.get("date_to")),
            
            oper_type=row.get("supplier_oper_name"),
            retail_amount=row.get("retail_amount", 0),
            amount=row.get("ppvz_for_pay", 0),
            delivery_rub=row.get("delivery_rub", 0),
            
            # --- НОВЫЕ ПОЛЯ ---
            penalty=row.get("penalty", 0),
            additional_payment=row.get("additional_payment", 0),
            commission_percent=row.get("commission_percent", 0),
            warehouse_name=row.get("office_name"), # Иногда это office_name или site_country
            
            order_dt=parse_dt(row.get("rr_dt")),
            sale_dt=parse_dt(row.get("rd_dt"))
        )
        db.add(record)
        new_records += 1
            
    await db.commit()
    return {"status": "success", "new_records": new_records, "total_found": len(report_data)}

@app.get("/analytics/finance_dashboard")
async def get_finance_dashboard(db: AsyncSession = Depends(database.get_db)):
    """Готовит данные для графика на основе ФИНАНСОВОГО отчета"""
    
    # 1. Сумма продаж (oper_type = 'Продажа')
    q_sales = select(models.FinanceRecord).filter(models.FinanceRecord.oper_type == "Продажа")
    res_sales = await db.execute(q_sales)
    sales_rows = res_sales.scalars().all()
    
    # 2. Логистика
    q_logistics = select(models.FinanceRecord).filter(models.FinanceRecord.delivery_rub > 0)
    res_logistics = await db.execute(q_logistics)
    logistics_rows = res_logistics.scalars().all()
    
    return {
        "sales_count": len(sales_rows),
        "sales_sum": sum(r.amount for r in sales_rows),
        "logistics_sum": sum(r.delivery_rub for r in logistics_rows),
        # Вернем сырые данные для таблицы
        "records": [
            {
                "date": r.sale_dt or r.order_dt or r.date_from, 
                "type": r.oper_type, 
                "item": r.nm_id, 
                "amount": r.amount,
                "retail_amount": r.retail_amount,
                "logistics": r.delivery_rub
            } 
            for r in sales_rows + logistics_rows
        ]
    }

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
            "target": int(item["target_profit"]),
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
async def batch_update_prices(
    items: List[schemas.PriceUpdateReq],
    source: str = "manual_ui",
    db: AsyncSession = Depends(database.get_db),
):
    """Принимает список новых цен и отправляет их в WB"""

    if not items:
        return {"status": "empty"}

    try:
        changes = await repricer.apply_price_updates(
            db,
            (
                {
                    "nm_id": item.nm_id,
                    "new_price": item.new_price,
                    "new_discount": item.new_discount,
                    "reason": "manual_apply",
                }
                for item in items
            ),
            source=source,
            default_reason="manual_apply",
        )
        await db.commit()
    except RuntimeError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "success", "updated": len(changes), "changes": changes}
