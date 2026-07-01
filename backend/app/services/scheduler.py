import os

import aiohttp

from app import database
from app.services import notifier, repricer

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8111")


async def check_prices_job():
    print("⏰ [Scheduler] Price Lock: проверка фиксированных цен WB...")

    async with database.SessionLocal() as db:
        try:
            result = await repricer.run_background_repricing(db, source="scheduler_price_lock")
        except Exception as exc:
            print(f"💥 [Scheduler] Price Lock упал: {exc}")
            await notifier.send_job_error("Price Lock", str(exc))
            return

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
        print(f"📢 [Scheduler] Есть рекомендации к ручному разбору: {len(manual_alerts_batch)} товаров")
        await notifier.send_batch_alert(manual_alerts_batch)

    if result["changes"]:
        print(f"🔒 [Scheduler] Price Lock вернул цены у {len(result['changes'])} товаров")
        await notifier.send_auto_report(result)
    else:
        print("✅ [Scheduler] Price Lock завершился без корректировок.")


async def sync_finance_job():
    """Ночная задача: скачивает финансовый отчет через актуальный finance/v1 API."""
    print("🌙 [Scheduler] Ночная выгрузка финансового отчета...")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{BACKEND_URL}/analytics/sync_finance", json={"days": 7}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"✅ [Scheduler] Финансы обновлены. Новых строк: {data.get('new_records', 0)}")
                else:
                    print(f"❌ [Scheduler] Ошибка выгрузки финансов: {await resp.text()}")
        except Exception as exc:
            print(f"💥 [Scheduler] Ошибка соединения: {exc}")


async def sync_items_job():
    print("🔄 [Scheduler] Фоновое обновление номенклатуры WB...")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{BACKEND_URL}/items/import_from_wb") as resp:
                if resp.status == 200:
                    print("✅ [Scheduler] Номенклатура актуальна.")
                else:
                    print(f"❌ [Scheduler] Ошибка импорта товаров: {await resp.text()}")
        except Exception as exc:
            print(f"💥 [Scheduler] Ошибка соединения: {exc}")
