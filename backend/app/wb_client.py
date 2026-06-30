import requests
import os
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

class WBClient:

    def __init__(self):
        self.token = os.getenv("WB_API_TOKEN")
        self.headers = {
            "Authorization": self.token,
            "Content-Type": "application/json"
        }

    def _make_request(self, method, url, **kwargs):
        """Умная обертка для запросов с повторами"""
        retries = 3
        for i in range(retries):
            try:
                response = requests.request(method, url, headers=self.headers, **kwargs)
                
                # Если успех - отдаем сразу
                if response.status_code == 200:
                    return response.json()
                
                # Если 429 (Слишком часто) - ждем и повторяем
                if response.status_code == 429:
                    wait_time = 60 # Ждем 1 минуту
                    logger.warning(f"WB Limit (429). Ждем {wait_time} сек...")
                    print(f"⏳ WB перегружен. Попытка {i+1}/{retries}. Ждем минуту...")
                    time.sleep(wait_time)
                    continue
                
                # Если 401 (Токен) - сразу ошибка
                if response.status_code == 401:
                    logger.error("Ошибка 401: Неверный токен!")
                    raise Exception("Токен не подходит или просрочен")

                response.raise_for_status()
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Ошибка сети: {e}")
                if i == retries - 1: # Если последняя попытка
                    raise e
                time.sleep(5)
        return []

    def get_cards(self):
        url = "https://content-api.wildberries.ru/content/v2/get/cards/list"
        payload = {"settings": {"cursor": {"limit": 100}, "filter": {"withPhoto": -1}}}
        
        data = self._make_request("POST", url, json=payload)
        
        if isinstance(data, dict):
            raw_cards = data.get("cards", [])
            cleaned = []
            for c in raw_cards:
                photos = c.get("photos", [])
                
                # --- УЛУЧШЕНИЕ: Ищем название ---
                # WB хранит название в поле 'title' или 'subjectName'
                # Если название пустое, соберем его из Бренда + Предмета
                title = c.get("title") or ""
                if not title:
                    brand = c.get("brand", "")
                    subject = c.get("subjectName", "Товар")
                    title = f"{subject} {brand}".strip()
                    
                cleaned.append({
                    "nm_id": c.get("nmID"),
                    "vendor_code": c.get("vendorCode"),
                    "name": title, # <-- Теперь здесь нормальное имя
                    "photo_url": photos[0].get("big") if photos else None
                })
            return cleaned
        return []

    def get_financial_report(self, date_from: str, date_to: str):
        """Скачивает Детализированный отчет (V5)"""
        url = "https://statistics-api.wildberries.ru/api/v5/supplier/reportDetailByPeriod"
        
        params = {
            "dateFrom": date_from,
            "dateTo": date_to
        }
        
        print(f"💰 Запрос ФИНАНСОВ (V5) с {date_from} по {date_to}")
        
        return self._make_request("GET", url, params=params)

    def get_prices(self):
        url = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"
        data = self._make_request("GET", url, params={"limit": 100, "filterPrice": -1})
        
        price_map = {}
        if isinstance(data, dict):
            goods = data.get("data", {}).get("listGoods", [])
            for g in goods:
                sizes = g.get("sizes", [])
                base = sizes[0].get("price", 0) if sizes else 0
                disc = g.get("discount", 0)
                price_map[g.get("nmID")] = {
                    "wb_price_base": base,
                    "wb_discount": disc,
                    "wb_price_final": base * (1 - disc/100)
                }
        return price_map

    def get_orders(self, date_from: str):
        """Умная загрузка заказов: пытается скачать частями, если общий запрос пуст"""
        url = "https://statistics-api.wildberries.ru/api/v1/supplier/orders"
        
        # 1. Сначала пробуем "в лоб" (как раньше)
        print(f"📥 Попытка 1: Запрос заказов с {date_from}")
        data = self._make_request("GET", url, params={"dateFrom": date_from if "T" in date_from else f"{date_from}T00:00:00", "flag": 0}) # flag 0 надежнее для свежих
        
        if data: 
            return data
            
        # 2. Если пусто - пробуем "Нарезку" за последние 30 дней по неделям
        print("⚠️ Общий список пуст. Включаем режим 'Нарезки' (Chunk Load)...")
        all_orders = []
        
        from datetime import datetime, timedelta
        
        # Берем последние 45 дней
        end_date = datetime.now()
        start_date = end_date - timedelta(days=45)
        
        current_start = start_date
        while current_start < end_date:
            current_end = current_start + timedelta(days=15) # Шаг 15 дней
            
            d_from = current_start.strftime("%Y-%m-%dT00:00:00")
            print(f"   🔎 Сканируем период: {d_from}")
            
            # flag=0 (только изменения) часто работает лучше для недавнего прошлого
            chunk = self._make_request("GET", url, params={"dateFrom": d_from, "flag": 0})
            if chunk:
                print(f"   ✅ Найдено {len(chunk)} шт.")
                all_orders.extend(chunk)
            
            current_start = current_end
            time.sleep(1) # Пауза, чтобы не получить 429
            
        return all_orders

    def get_sales(self, date_from: str):
        """Аналогичная умная загрузка для продаж"""
        url = "https://statistics-api.wildberries.ru/api/v1/supplier/sales"
        # Для продаж логика такая же
        print(f"💰 Попытка 1: Запрос продаж с {date_from}")
        data = self._make_request("GET", url, params={"dateFrom": date_from if "T" in date_from else f"{date_from}T00:00:00", "flag": 0})
        
        if data: return data
        
        print("⚠️ Продажи пусто. Включаем 'Нарезку'...")
        all_sales = []
        from datetime import datetime, timedelta
        end_date = datetime.now()
        start_date = end_date - timedelta(days=60) # Ищем за 60 дней
        
        current_start = start_date
        while current_start < end_date:
            d_from = current_start.strftime("%Y-%m-%dT00:00:00")
            chunk = self._make_request("GET", url, params={"dateFrom": d_from, "flag": 0})
            if chunk:
                all_sales.extend(chunk)
            current_start += timedelta(days=15)
            time.sleep(1)
            
        return all_sales

    def update_prices(self, updates: list):
        """
        Отправляет новые цены на WB.
        updates - это список словарей: [{"nmID": 123, "price": 5000, "discount": 35}]
        """
        url = "https://discounts-prices-api.wildberries.ru/api/v2/upload/task"
        
        # WB требует такой формат: {"data": [{"nmID": ..., "price": ..., "discount": ...}]}
        # Важно: "price" - это розничная цена до скидки, а "discount" - скидка продавца.
        
        payload = {"data": updates}
        
        print(f"📤 ОТПРАВКА ЦЕН НА WB: {len(updates)} товаров")
        
        try:
            # Используем POST
            response = requests.post(url, json=payload, headers=self.headers)
            
            if response.status_code == 200:
                print("✅ Цены успешно обновлены (создана задача)!")
                return True
            elif response.status_code == 429:
                print("⏳ Лимит WB. Попробуйте позже.")
                return False
            else:
                print(f"❌ Ошибка обновления цен: {response.text}")
                return False
                
        except Exception as e:
            print(f"Ошибка сети: {e}")
            return False

wb = WBClient()
