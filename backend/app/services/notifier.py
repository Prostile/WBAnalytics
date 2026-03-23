import os
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

TG_TOKEN = os.getenv("TG_BOT_TOKEN")
ADMIN_ID = os.getenv("TG_ADMIN_ID")

async def send_batch_alert(items: list):
    """
    Присылает сводную таблицу товаров, требующих внимания.
    items = [{'name': '...', 'profit': 100, 'target': 200, 'new_price': 5000, 'nm_id': 123}, ...]
    """
    if not TG_TOKEN or not ADMIN_ID: return

    bot = Bot(token=TG_TOKEN)
    
    # Заголовок
    text = f"⚠️ <b>Внимание! Низкая маржа у {len(items)} товаров</b>\n\n"
    
    # Формируем список (максимум 5 штук, чтобы не забить экран)
    max_show = 5
    for i, item in enumerate(items[:max_show]):
        text += (
            f"🔹 <b>{item['name']}</b>\n"
            f"   Прибыль: {item['profit']} ₽ (Цель: {item['target']})\n"
            f"   ⬇️ Реком. цена: <b>{item['new_price']} ₽</b>\n\n"
        )
    
    if len(items) > max_show:
        text += f"<i>...и еще {len(items) - max_show} товаров.</i>\n"
        
    text += "Перейдите в панель управления для массового изменения."

    # Кнопки для ТОП-3 товаров (быстрые действия)
    keyboard_rows = []
    for item in items[:3]:
        btn_text = f"✅ {item['name'][:10]}.. -> {item['new_price']}₽"
        btn_data = f"set_price:{item['nm_id']}:{item['new_price']}"
        keyboard_rows.append([InlineKeyboardButton(text=btn_text, callback_data=btn_data)])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        print(f"Ошибка ТГ: {e}")
    finally:
        await bot.session.close()

async def send_auto_report(run_result: dict):
    """Базовая сводка по авто-коррекциям. Детализация будет расширяться отдельно."""
    changes = run_result.get("changes", [])
    if not TG_TOKEN or not ADMIN_ID or not changes:
        return

    total_delta = sum(int(change.get("price_delta", 0)) for change in changes)
    text = (
        f"🤖 <b>Фоновая оптимизация завершена</b>\n\n"
        f"Проверено товаров: <b>{run_result.get('checked_items', 0)}</b>\n"
        f"Изменено: <b>{len(changes)}</b>\n"
        f"Суммарная дельта цен: <b>{total_delta:+,} ₽</b>"
    )

    bot = Bot(token=TG_TOKEN)
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка ТГ: {e}")
    finally:
        await bot.session.close()


async def send_job_error(job_name: str, error_message: str):
    if not TG_TOKEN or not ADMIN_ID:
        return

    bot = Bot(token=TG_TOKEN)
    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💥 <b>{job_name}</b>\n\n<code>{error_message}</code>",
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"Ошибка ТГ: {e}")
    finally:
        await bot.session.close()
