import aiohttp
import os

from app import database
from app.services import notifier, repricer

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8111")


async def check_prices_job():
    print("⏰ [Scheduler] Проверка маржинальности и цен...")

    async with database.SessionLocal() as db:
        try:
            result = await repricer.run_background_repricing(db)
        except Exception as exc:
            print(f"💥 [Scheduler] Фоновая оптимизация упала: {exc}")
            await notifier.send_job_error("Фоновая оптимизация", str(exc))
            return

    manual_alerts_batch = [
        {
            "name": item["name"] or str(item["nm_id"]),
            "profit": int(item["current_profit"]),
            "target": int(item["target_profit"]),
            "new_price": int(item["recommended_price_retail"]),
            "nm_id": item["nm_id"],
        }
        for item in result["manual_alerts"]
    ]

    if manual_alerts_batch:
        print(f"📢 [Scheduler] Отправляем ручные алерты ({len(manual_alerts_batch)} товаров)")
        await notifier.send_batch_alert(manual_alerts_batch)

    if result["changes"]:
        print(f"🚀 [Scheduler] AUTO скорректировал {len(result['changes'])} товаров")
        await notifier.send_auto_report(result)
    else:
        print("✅ [Scheduler] Фоновая оптимизация завершилась без изменений.")


async def sync_finance_job():
    """Ночная задача: скачивает отчет V5 за последние 7 дней для актуализации."""
    print("🌙 [Scheduler] Ночная выгрузка отчета V5...")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{BACKEND_URL}/analytics/sync_finance", json={"days": 7}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"✅ [Scheduler] Отчет V5 обновлен! Строк: {data.get('total_found', 0)}")
                else:
                    print(f"❌ [Scheduler] Ошибка выгрузки V5: {await resp.text()}")
        except Exception as exc:
            print(f"💥 [Scheduler] Ошибка соединения: {exc}")


async def sync_items_job():
    """Задача: обновляет базу товаров (новые карточки, фото, названия)."""
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
