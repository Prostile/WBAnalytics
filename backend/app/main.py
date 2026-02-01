from fastapi import FastAPI, Depends, HTTPException
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from . import models, schemas, database, wb_client
from .services import unit_economics

# --- ИМПОРТЫ ДЛЯ SCHEDULER ---
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.scheduler import check_prices_job

# Создаем планировщик
scheduler = AsyncIOScheduler()

# Оборачиваем старт приложения
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. СОЗДАЕМ ТАБЛИЦЫ В БД (ЭТОГО НЕ ХВАТАЛО!)
    print("📦 Создаем таблицы в БД...")
    await database.init_db()
    
    # 2. ЗАПУСКАЕМ ПЛАНИРОВЩИК
    print("🟢 Запуск Планировщика Цен...")
    scheduler.add_job(check_prices_job, 'interval', minutes=30)
    scheduler.start()
    
    yield # Работа приложения
    
    print("🔴 Остановка...")
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

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
    result = await db.execute(select(models.Item).filter(models.Item.nm_id == item.nm_id))
    db_item = result.scalars().first()
    
    if db_item:
        for key, value in item.dict().items():
            setattr(db_item, key, value)
    else:
        db_item = models.Item(**item.dict())
        db.add(db_item)
    
    await db.commit()
    await db.refresh(db_item)
    return db_item

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
                "logistics": r.delivery_rub
            } 
            for r in sales_rows + logistics_rows
        ]
    }

@app.get("/repricer/status")
async def get_repricer_status(db: AsyncSession = Depends(database.get_db)):
    result = await db.execute(select(models.Item).filter(models.Item.is_active))
    items = result.scalars().all()
    
    report = []
    
    for item in items:
        # Считаем математику
        optimal = unit_economics.calculate_optimal_price(
            target_profit=item.target_profit,
            cost_price=item.cost_price,
            logistics=item.logistics_cost,
            tax_rate=item.tax_rate,
            commission=item.wb_commission,
            current_discount=item.wb_discount # <--- ВАЖНО: Используем текущую скидку карты!
        )
        
        # Считаем текущую чистую прибыль
        current_price = item.wb_price_final # Цена клиента
        current_profit = (
            current_price 
            - item.cost_price 
            - item.logistics_cost 
            - (current_price * item.wb_commission) 
            - (current_price * item.tax_rate)
        )
        
        # --- ФИКС ЗДЕСЬ ---
        # Нам нужно отправить на WB "Высокую цену" (Retail), 
        # чтобы после скидки получилась "Финальная" (Final).
        
        # Если скидки нет, то Retail = Final
        rec_retail = optimal.get("recommended_retail_price") 
        rec_final = optimal.get("recommended_final_price")

        report.append({
            "nm_id": item.nm_id,
            "vendor_code": item.vendor_code,
            "photo_url": item.photo_url,
            "mode": item.repricer_mode,
            "wb_discount": item.wb_discount, # Передаем скидку на фронт, чтобы видеть её
            
            # ФАКТ
            "current_price": current_price,
            "current_profit": round(current_profit, 0),
            
            # ПЛАН
            "target_profit": item.target_profit,
            
            # --- ИСПРАВЛЕНИЕ: Передаем ОБЕ цены ---
            "recommended_price_retail": rec_retail, # Эту отправим на WB (например 12000)
            "recommended_price_final": rec_final,   # Эту увидит клиент (например 6200)
            
            # Diff считаем по финальной цене (чтобы понимать масштаб изменений для клиента)
            "diff_price": rec_final - current_price,
            
            "status": "OK" if abs(item.target_profit - current_profit) < 100 else "⚠️ MISMATCH"
        })
        
    return report

@app.post("/repricer/batch_update")
async def batch_update_prices(items: List[schemas.PriceUpdateReq], db: AsyncSession = Depends(database.get_db)):
    """Принимает список новых цен и отправляет их в WB"""
    
    # 1. Готовим данные для WB
    # WB API "upload/task" принимает: nmID, price (розничная)
    wb_payload = [{"nmID": item.nm_id, "price": int(item.new_price)} for item in items]
    
    if not wb_payload:
        return {"status": "empty"}

    # 2. Отправляем в WB
    success = wb_client.wb.update_prices(wb_payload)
    
    if not success:
        raise HTTPException(status_code=500, detail="Не удалось обновить цены на WB")
    
    # 3. Обновляем локальную базу (чтобы мы сразу видели изменения, не ждали синхронизации)
    count = 0
    for item in items:
        db_item = await db.execute(select(models.Item).filter(models.Item.nm_id == item.nm_id))
        record = db_item.scalars().first()
        if record:
            # Мы меняем БАЗОВУЮ цену. Финальная пересчитается, если знаем скидку
            record.wb_price_base = item.new_price
            # Пересчет финальной (примерный)
            if record.wb_discount:
                record.wb_price_final = item.new_price * (1 - record.wb_discount/100)
            count += 1
            
    await db.commit()
    
    return {"status": "success", "updated": count}