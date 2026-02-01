import os
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Берем токен из .env (загружается в main.py)
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
ADMIN_ID = os.getenv("TG_ADMIN_ID")

async def send_manual_alert(item_name: str, current_profit: int, target_profit: int, new_price: int, nm_id: int):
    """
    Отправляет сообщение с кнопкой 'Применить цену'
    """
    if not TG_TOKEN or not ADMIN_ID:
        print("⚠️ TG токен не задан!")
        return

    bot = Bot(token=TG_TOKEN)
    
    text = (
        f"⚠️ <b>Низкая маржинальность!</b>\n"
        f"📦 Товар: {item_name}\n"
        f"💰 Прибыль сейчас: {current_profit} ₽\n"
        f"🎯 Цель: {target_profit} ₽\n\n"
        f"Рекомендация: Установить цену <b>{new_price} ₽</b>"
    )
    
    # Кнопка, которая вызовет действие (callback)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Установить {new_price} ₽", callback_data=f"set_price:{nm_id}:{new_price}")]
    ])
    
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        print(f"Ошибка отправки в ТГ: {e}")
    finally:
        await bot.session.close()

async def send_auto_report(item_name: str, old_price: int, new_price: int):
    """
    Отправляет отчет об авто-изменении
    """
    if not TG_TOKEN or not ADMIN_ID: return

    bot = Bot(token=TG_TOKEN)
    text = (
        f"🤖 <b>Авто-Репрайсер</b>\n"
        f"📦 {item_name}\n"
        f"🔄 Цена изменена: {old_price} -> <b>{new_price} ₽</b>\n"
        f"Целевая прибыль восстановлена."
    )
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка ТГ: {e}")
    finally:
        await bot.session.close()