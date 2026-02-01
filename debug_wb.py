import requests
import json
import time

# ==========================================
# ВСТАВЬТЕ ВАШ ТОКЕН СЮДА (БЕЗ ПРОБЕЛОВ)
TOKEN = "eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjMsImVudCI6MSwiZXhwIjoxNzg1NjUxNDQyLCJmb3IiOiJzZWxmIiwiaWQiOiIwMTljMTU0Ni0xY2Y2LTc4N2YtYTZlMC02NTNiYzRmZDJlZWEiLCJpaWQiOjEzNjM4MzI0LCJvaWQiOjQyMTM5OTgsInMiOjgxNjYyLCJzaWQiOiIzZTM0MDk0Yy05MTYwLTRmZWItODhjYS0zNzEwMTg3NmIyNGIiLCJ0IjpmYWxzZSwidWlkIjoxMzYzODMyNH0.Y_Gyy5oiA3PPNCUpGblOwfsSMKrmwRkHSrhqcsJi2Eb-7q25rKgFVH26rvXkBw4F5eKowpICCPuIKigDxzZTTw"
# ==========================================

HEADERS = {
    "Authorization": TOKEN,
    "Content-Type": "application/json"
}

# Дата начала времен (чтобы точно зацепить архив)
DATE_FROM = "2023-01-01T00:00:00"

def test_endpoint(name, method, url, params=None, json_data=None):
    print(f"\n--- 🔍 ПРОВЕРКА: {name} ---")
    print(f"📡 URL: {url}")
    
    try:
        if method == "GET":
            response = requests.get(url, params=params, headers=HEADERS, timeout=15)
        else:
            response = requests.post(url, json=json_data, headers=HEADERS, timeout=15)
            
        print(f"📩 Статус: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            # Разные форматы ответов у WB
            if isinstance(data, dict):
                # Бывает ответ {"cards": [...]} или {"data": [...]} или просто {...}
                if "cards" in data:
                    items = data["cards"]
                    print(f"✅ УСПЕХ! Найдено: {len(items)} шт.")
                    if items: print(f"   Пример: {items[0].get('vendorCode')}")
                elif "orders" in data: # Для FBS
                    items = data["orders"]
                    print(f"✅ УСПЕХ! Найдено: {len(items)} активных заказов FBS.")
                else:
                    print(f"✅ Ответ получен (Словарь). Ключи: {list(data.keys())}")
            elif isinstance(data, list):
                print(f"✅ УСПЕХ! Найдено записей: {len(data)}")
                if len(data) > 0:
                    # Попытка найти дату в первом элементе
                    sample = data[0]
                    date = sample.get('date') or sample.get('lastChangeDate') or 'Нет даты'
                    print(f"   Пример первой записи: {str(sample)[:100]}...")
                    print(f"   Дата записи: {date}")
            else:
                print("✅ Ответ получен, но формат странный.")
        
        elif response.status_code == 401:
            print("❌ ОШИБКА 401: Нет доступа! Проверьте галочку для этого раздела.")
        elif response.status_code == 429:
            print("⏳ ОШИБКА 429: Лимит запросов. WB просит подождать.")
        else:
            print(f"❌ ОШИБКА {response.status_code}: {response.text[:200]}")
            
    except Exception as e:
        print(f"💥 Сбой соединения: {e}")

def run_diagnostics():
    print("🚀 ЗАПУСК ПОЛНОЙ ДИАГНОСТИКИ WB API...\n")

    # 1. КОНТЕНТ (Карточки) - Проверка связи
    test_endpoint(
        "1. Карточки товара (Content)", 
        "POST", 
        "https://content-api.wildberries.ru/content/v2/get/cards/list",
        json_data={"settings": {"cursor": {"limit": 10}, "filter": {"withPhoto": -1}}}
    )

    # 2. СКЛАД (Статистика) - Самый быстрый тест
    test_endpoint(
        "2. Складские остатки (Statistics)", 
        "GET", 
        "https://statistics-api.wildberries.ru/api/v1/supplier/stocks",
        params={"dateFrom": DATE_FROM}
    )

    # 3. ЗАКАЗЫ АРХИВ (Статистика)
    test_endpoint(
        "3. История Заказов - АРХИВ (Statistics flag=1)", 
        "GET", 
        "https://statistics-api.wildberries.ru/api/v1/supplier/orders",
        params={"dateFrom": DATE_FROM, "flag": 1}
    )

    # 4. ЗАКАЗЫ СВЕЖИЕ (Статистика)
    test_endpoint(
        "4. История Заказов - НЕДАВНИЕ (Statistics flag=0)", 
        "GET", 
        "https://statistics-api.wildberries.ru/api/v1/supplier/orders",
        params={"dateFrom": DATE_FROM, "flag": 0}
    )
    
    # 5. ПРОДАЖИ (Статистика)
    test_endpoint(
        "5. История Продаж/Выкупов (Statistics flag=1)", 
        "GET", 
        "https://statistics-api.wildberries.ru/api/v1/supplier/sales",
        params={"dateFrom": DATE_FROM, "flag": 1}
    )

    # 6. ПОСТАВКИ (FBO) - Если вы грузили на склад WB
    test_endpoint(
        "6. Поставки FBO (Incomes)", 
        "GET", 
        "https://statistics-api.wildberries.ru/api/v1/supplier/incomes",
        params={"dateFrom": DATE_FROM}
    )

    # 7. СБОРОЧНЫЕ ЗАДАНИЯ (FBS) - Если вы торгуете со своего склада
    # Это API Маркетплейса, не Статистики. Оно показывает НОВЫЕ заказы (на сборку).
    test_endpoint(
        "7. Новые сборочные задания FBS (Marketplace)", 
        "GET", 
        "https://marketplace-api.wildberries.ru/api/v3/orders/new"
    )
    
    # 8. АРХИВ FBS (Marketplace) - Отгруженные заказы
    test_endpoint(
        "8. Архив сборочных заданий FBS (Marketplace)", 
        "GET", 
        "https://marketplace-api.wildberries.ru/api/v3/orders",
        params={"limit": 10, "next": 0, "dateFrom": 1704067200} # dateFrom в timestamp (01.01.2024)
    )

if __name__ == "__main__":
    run_diagnostics()