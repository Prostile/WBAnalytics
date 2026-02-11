from sqlalchemy.future import select
from app import models, database
from app.services import unit_economics, notifier
from app.wb_client import wb
import asyncio
import aiohttp
import os

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8111")

# --- СТАРЫЕ ЗАДАЧИ (ЦЕНЫ) ---
async def check_prices_job():
    print("⏰ [Scheduler] Проверка маржинальности и цен...")
    
    async with database.SessionLocal() as db:
        result = await db.execute(select(models.Item).filter(models.Item.is_active == True))
        items = result.scalars().all()
        
        manual_alerts_batch = []
        auto_updates_batch = []
        
        for item in items:
            optimal = unit_economics.calculate_optimal_price(
                target_profit=item.target_profit, cost_price=item.cost_price,
                logistics=item.logistics_cost, tax_rate=item.tax_rate,
                commission=item.wb_commission, current_discount=item.wb_discount
            )
            rec_retail = optimal.get("recommended_retail_price", 0)
            
            current_profit = (
                item.wb_price_final - item.cost_price - item.logistics_cost - 
                (item.wb_price_final * item.wb_commission) - (item.wb_price_final * item.tax_rate)
            )
            
            if item.target_profit - current_profit > 100 and rec_retail > 0:
                if item.repricer_mode == 'manual':
                    manual_alerts_batch.append({
                        "name": item.name or str(item.nm_id),
                        "profit": int(current_profit), "target": int(item.target_profit),
                        "new_price": int(rec_retail), "nm_id": item.nm_id
                    })
                elif item.repricer_mode == 'auto':
                    auto_updates_batch.append({"nmID": item.nm_id, "price": int(rec_retail)})

        if manual_alerts_batch:
            print(f"📢 Отправляем сводку в ТГ ({len(manual_alerts_batch)} товаров)")
            await notifier.send_batch_alert(manual_alerts_batch)
            
        if auto_updates_batch:
            print(f"🚀 AUTO: Обновляем цены на WB ({len(auto_updates_batch)} товаров)")
            wb.update_prices(auto_updates_batch)


# --- НОВЫЕ ЗАДАЧИ (СИНХРОНИЗАЦИЯ ДАННЫХ) ---

async def sync_finance_job():
    """Ночная задача: скачивает отчет V5 за последние 7 дней для актуализации."""
    print("🌙 [Scheduler] Ночная выгрузка отчета V5...")
    async with aiohttp.ClientSession() as session:
        try:
            # Бэкенд стучится в свой же API (localhost)
            async with session.post("f{BACKEND_URL}/analytics/sync_finance", json={"days": 7}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"✅ [Scheduler] Отчет V5 обновлен! Строк: {data.get('total_found', 0)}")
                else:
                    print(f"❌ [Scheduler] Ошибка выгрузки V5: {await resp.text()}")
        except Exception as e:
            print(f"💥 [Scheduler] Ошибка соединения: {e}")

async def sync_items_job():
    """Задача: обновляет базу товаров (новые карточки, фото, названия)."""
    print("🔄 [Scheduler] Фоновое обновление номенклатуры WB...")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post("f{BACKEND_URL}/items/import_from_wb") as resp:
                if resp.status == 200:
                    print("✅ [Scheduler] Номенклатура актуальна.")
                else:
                    print(f"❌ [Scheduler] Ошибка импорта товаров: {await resp.text()}")
        except Exception as e:
            print(f"💥 [Scheduler] Ошибка соединения: {e}")