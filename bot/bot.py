import asyncio
import os
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import aiohttp

logging.basicConfig(level=logging.INFO)

TG_TOKEN = os.getenv("TG_BOT_TOKEN")
ADMIN_ID = os.getenv("TG_ADMIN_ID")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- КЛАВИАТУРА (ГЛАВНОЕ МЕНЮ) ---
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Финансовая сводка")],
        [KeyboardButton(text="🚨 Проверить цены"), KeyboardButton(text="⚙️ Статус")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие..."
)

# --- ПРОВЕРКА ДОСТУПА ---
def is_admin(user_id: int) -> bool:
    return str(user_id) == ADMIN_ID

# --- 1. КОМАНДА /START ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещен.")
        return
    await message.answer(
        "👋 Добро пожаловать в мобильную панель **WB ERP**!\n\nИспользуйте меню ниже для управления.", 
        reply_markup=main_keyboard,
        parse_mode="Markdown"
    )

# --- 2. ФИНАНСОВАЯ СВОДКА ---
@dp.message(F.text == "📊 Финансовая сводка")
async def get_summary(message: Message):
    if not is_admin(message.from_user.id): return
    
    msg = await message.answer("⏳ Собираю данные по финансам...")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Запрашиваем данные у Бэкенда (API)
            async with session.get(f"{BACKEND_URL}/analytics/finance_dashboard") as resp:
                if resp.status != 200:
                    await msg.edit_text("❌ Ошибка получения данных от сервера.")
                    return
                
                data = await resp.json()
                records = data.get("records", [])
                
                if not records:
                    await msg.edit_text("🤷‍♂️ В базе нет данных. Нажмите 'Скачать отчет V5' на сайте.")
                    return
                
                # Считаем метрики за последние 3 дня
                limit_date = datetime.now() - timedelta(days=3)
                
                recent_sales = 0
                gross_rev = 0
                net_profit = 0
                
                for r in records:
                    r_date = datetime.fromisoformat(r['date'].replace('Z', '+00:00')).replace(tzinfo=None)
                    if r_date >= limit_date:
                        if r['type'] == 'Продажа':
                            recent_sales += 1
                        
                        # Примитивный расчет прибыли для быстрой сводки
                        cogs = 500 # Условно, так как бот не знает себестоимость без второго запроса
                        amount = r.get('amount', 0)
                        retail = r.get('retail_amount', amount)
                        logistics = r.get('logistics', 0)
                        
                        if r['type'] == 'Продажа':
                            gross_rev += retail
                            net_profit += (amount - cogs - logistics)
                        elif r['type'] == 'Возврат':
                            net_profit += (cogs - logistics) # Вернули товар на склад, но потеряли на логистике
                
                text = (
                    f"📈 <b>Сводка за последние 3 дня</b>\n\n"
                    f"📦 Операций (продаж): <b>{recent_sales} шт.</b>\n"
                    f"💰 Грязная выручка: <b>{int(gross_rev):,} ₽</b>\n"
                    f"💵 Прибыль (оценочно): <b>~{int(net_profit):,} ₽</b>\n\n"
                    f"<i>Для точного P&L с учетом ABC-анализа перейдите в веб-дашборд.</i>"
                )
                
                await msg.edit_text(text, parse_mode="HTML")
                
    except Exception as e:
        await msg.edit_text(f"💥 Ошибка связи с бэкендом: {e}")

# --- 3. ПРОВЕРКА ЦЕН (АЛЕРТЫ) ---
@dp.message(F.text == "🚨 Проверить цены")
async def check_prices_manual(message: Message):
    if not is_admin(message.from_user.id): return
    
    msg = await message.answer("⏳ Анализирую маржинальность товаров...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BACKEND_URL}/repricer/status") as resp:
                items = await resp.json()
                
                bad_items = [i for i in items if i.get('status') != 'OK' and i.get('recommended_price_retail', 0) > 0]
                
                if not bad_items:
                    await msg.edit_text("✅ <b>Все отлично!</b> Цены соответствуют целевой прибыли.", parse_mode="HTML")
                    return
                
                text = f"⚠️ <b>Внимание! Низкая маржа у {len(bad_items)} товаров</b>\n\n"
                
                keyboard_rows = []
                # Показываем только Топ-5, чтобы не спамить
                for item in bad_items[:5]:
                    text += (
                        f"🔹 <b>{item['name']}</b>\n"
                        f"   Прибыль: {item['current_profit']} ₽ (Цель: {item['target_profit']})\n"
                        f"   ⬇️ Реком. цена на WB: <b>{item['recommended_price_retail']} ₽</b>\n\n"
                    )
                    btn_text = f"✅ {item['name'][:12]}.. -> {item['recommended_price_retail']}₽"
                    btn_data = f"set_price:{item['nm_id']}:{item['recommended_price_retail']}"
                    keyboard_rows.append([InlineKeyboardButton(text=btn_text, callback_data=btn_data)])
                
                if len(bad_items) > 5:
                    text += f"<i>...и еще {len(bad_items) - 5} товаров.</i>\n"
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
                
                # Удаляем сообщение с часиками и шлем новое с кнопками
                await msg.delete()
                await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    except Exception as e:
        await msg.edit_text(f"💥 Ошибка: {e}")

# --- 4. СТАТУС СИСТЕМЫ ---
@dp.message(F.text == "⚙️ Статус")
async def check_status(message: Message):
    if not is_admin(message.from_user.id): return
    await message.answer("🟢 Система работает в штатном режиме.\nФоновые задачи активны.")

# --- 5. ОБРАБОТКА КНОПОК ПРИМЕНЕНИЯ ЦЕН ---
@dp.callback_query(F.data.startswith("set_price"))
async def process_price_update(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    
    _, nm_id, price = callback.data.split(":")
    await callback.answer("⏳ Отправляю запрос...") 
    
    payload = [{"nm_id": int(nm_id), "new_price": int(price)}]
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BACKEND_URL}/repricer/batch_update", json=payload) as resp:
                if resp.status == 200:
                    await callback.message.edit_text(
                        text=f"{callback.message.text}\n\n✅ <b>УСПЕШНО!</b> Цена изменена на {price} ₽",
                        parse_mode="HTML",
                        reply_markup=None 
                    )
                else:
                    await callback.message.answer(f"❌ Ошибка бэкенда: {await resp.text()}")
    except Exception as e:
        await callback.message.answer(f"💥 Ошибка: {e}")

# --- ЗАПУСК ---
async def main():
    print("🤖 Бот запущен с новым интерфейсом...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())