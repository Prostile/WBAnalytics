import asyncio
import os
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
import aiohttp

# Настройка логов
logging.basicConfig(level=logging.INFO)

# Берем настройки из .env (Docker их передаст)
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
ADMIN_ID = os.getenv("TG_ADMIN_ID") # Чтобы слушаться только вас
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000") # Адрес мозга

# Инициализация
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- 1. КОМАНДА /START ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = str(message.from_user.id)
    
    if user_id == ADMIN_ID:
        await message.answer(f"👋 Привет, Хозяин! Система WB ERP готова к работе.\nТвой ID: {user_id} (совпадает с конфигом).")
    else:
        await message.answer(f"⛔ Доступ запрещен. Твой ID: {user_id}\nДобавь его в .env файл как TG_ADMIN_ID.")

# --- 2. ОБРАБОТКА КНОПКИ 'УСТАНОВИТЬ ЦЕНУ' ---
# Формат данных в кнопке: "set_price:NM_ID:NEW_PRICE"
@dp.callback_query(F.data.startswith("set_price"))
async def process_price_update(callback: CallbackQuery):
    # Разбираем данные из кнопки
    _, nm_id, price = callback.data.split(":")
    
    await callback.answer("⏳ Отправляю запрос...") # Всплывашка "Часики"
    
    # Формируем запрос к нашему Бэкенду
    payload = [
        {
            "nm_id": int(nm_id),
            "new_price": int(price)
        }
    ]
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BACKEND_URL}/repricer/batch_update", json=payload) as resp:
                if resp.status == 200:
                    # Если Бэкенд сказал ОК
                    await callback.message.edit_text(
                        text=f"{callback.message.text}\n\n✅ <b>УСПЕШНО!</b> Цена изменена на {price} ₽",
                        parse_mode="HTML",
                        reply_markup=None # Убираем кнопку, чтобы не нажать дважды
                    )
                else:
                    error_text = await resp.text()
                    await callback.message.answer(f"❌ Ошибка бэкенда: {error_text}")
                    
    except Exception as e:
        await callback.message.answer(f"💥 Ошибка связи с сервером: {e}")

# --- ЗАПУСК ---
async def main():
    print("🤖 Бот запущен и слушает...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())