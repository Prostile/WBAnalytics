from sqlalchemy.future import select
from app import models, database
from app.services import unit_economics, notifier
from app.wb_client import wb
import asyncio

async def check_prices_job():
    print("⏰ [Scheduler] Запуск проверки цен...")
    
    # Создаем новую сессию БД
    async with database.SessionLocal() as db:
        result = await db.execute(select(models.Item).filter(models.Item.is_active))
        items = result.scalars().all()
        
        updates_batch = [] # Для авто-режима (чтобы отправить пачкой)
        
        for item in items:
            # 1. Считаем математику
            optimal = unit_economics.calculate_optimal_price(
                target_profit=item.target_profit,
                cost_price=item.cost_price,
                logistics=item.logistics_cost,
                tax_rate=item.tax_rate,
                commission=item.wb_commission,
                current_discount=item.wb_discount
            )
            
            rec_retail = optimal.get("recommended_retail_price", 0)
            
            # 2. Считаем текущую прибыль
            current_profit = (
                item.wb_price_final 
                - item.cost_price 
                - item.logistics_cost 
                - (item.wb_price_final * item.wb_commission) 
                - (item.wb_price_final * item.tax_rate)
            )
            
            # 3. Проверяем отклонение (например, если цель не выполняется на > 100 руб)
            diff = item.target_profit - current_profit
            
            if diff > 100 and rec_retail > 0:
                print(f"❗ {item.name}: Теряем {diff} руб. Режим: {item.repricer_mode}")
                
                # РЕЖИМ: MANUAL
                if item.repricer_mode == 'manual':
                    # Шлем кнопку в ТГ
                    await notifier.send_manual_alert(
                        item_name=item.name or str(item.nm_id),
                        current_profit=int(current_profit),
                        target_profit=int(item.target_profit),
                        new_price=int(rec_retail),
                        nm_id=item.nm_id
                    )
                
                # РЕЖИМ: AUTO
                elif item.repricer_mode == 'auto':
                    # Добавляем в список на обновление
                    updates_batch.append({"nmID": item.nm_id, "price": int(rec_retail)})
                    
                    # Шлем отчет
                    await notifier.send_auto_report(
                        item_name=item.name, 
                        old_price=int(item.wb_price_base), 
                        new_price=int(rec_retail)
                    )
        
        # Если есть авто-обновления - отправляем их в WB
        if updates_batch:
            print(f"🚀 AUTO: Обновляем {len(updates_batch)} товаров...")
            wb.update_prices(updates_batch)