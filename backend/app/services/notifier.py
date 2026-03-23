import os
from html import escape
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

TG_TOKEN = os.getenv("TG_BOT_TOKEN")
ADMIN_ID = os.getenv("TG_ADMIN_ID")


def _rub(value: float) -> str:
    return f"{int(round(value)):,} ₽".replace(",", " ")

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
            f"🔹 <b>{escape(item['name'])}</b>\n"
            f"   Прибыль: {_rub(item['profit'])} (Цель: {_rub(item['target'])})\n"
            f"   ⬇️ Реком. цена: <b>{_rub(item['new_price'])}</b>\n\n"
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
    changes = run_result.get("changes", [])
    if not TG_TOKEN or not ADMIN_ID or not changes:
        return

    total_delta = sum(float(change.get("price_delta", 0) or 0) for change in changes)
    text_lines = [
        "🤖 <b>Фоновая оптимизация завершена</b>",
        "",
        f"Проверено товаров: <b>{run_result.get('checked_items', 0)}</b>",
        f"Авто-готово: <b>{run_result.get('eligible_items', 0)}</b>",
        f"Изменено: <b>{len(changes)}</b>",
        f"На ручной разбор: <b>{run_result.get('manual_items', 0)}</b>",
        f"Цены с WB обновлены у: <b>{run_result.get('price_sync_items', 0)}</b>",
        f"Суммарная дельта цен: <b>{_rub(total_delta)}</b>",
        "",
        "<b>Что изменилось:</b>",
    ]

    max_show = 7
    for change in changes[:max_show]:
        direction = "⬆️" if float(change.get("price_delta", 0) or 0) >= 0 else "⬇️"
        text_lines.extend(
            [
                f"{direction} <b>{escape(change['name'])}</b>",
                (
                    f"{_rub(change['old_price_retail'])} → <b>{_rub(change['new_price_retail'])}</b> "
                    f"({change['price_delta']:+.0f} ₽ / {change['price_delta_percent']:+.1f}%)"
                ),
                (
                    f"Прибыль: {_rub(change['old_profit'])} → {_rub(change['new_profit'])} "
                    f"(цель {_rub(change['target_profit'])})"
                ),
                "",
            ]
        )

    if len(changes) > max_show:
        text_lines.append(f"<i>...и еще {len(changes) - max_show} товаров.</i>")

    text = "\n".join(text_lines).strip()

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
            text=f"💥 <b>{escape(job_name)}</b>\n\n<code>{escape(error_message)}</code>",
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"Ошибка ТГ: {e}")
    finally:
        await bot.session.close()
