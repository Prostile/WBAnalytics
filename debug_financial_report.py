import requests
import time
from datetime import datetime

# ВАШ ТОКЕН
TOKEN = "eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjMsImVudCI6MSwiZXhwIjoxNzg1NjUxNDQyLCJmb3IiOiJzZWxmIiwiaWQiOiIwMTljMTU0Ni0xY2Y2LTc4N2YtYTZlMC02NTNiYzRmZDJlZWEiLCJpaWQiOjEzNjM4MzI0LCJvaWQiOjQyMTM5OTgsInMiOjgxNjYyLCJzaWQiOiIzZTM0MDk0Yy05MTYwLTRmZWItODhjYS0zNzEwMTg3NmIyNGIiLCJ0IjpmYWxzZSwidWlkIjoxMzYzODMyNH0.Y_Gyy5oiA3PPNCUpGblOwfsSMKrmwRkHSrhqcsJi2Eb-7q25rKgFVH26rvXkBw4F5eKowpICCPuIKigDxzZTTw"

def check_financial_report():
    print("🚀 ЗАПУСК: Генерация Финансового Отчета (Детализация)...")
    
    url = "https://statistics-api.wildberries.ru/api/v5/supplier/reportDetailByPeriod"
    
    # Запрашиваем отчет за широкий диапазон (например, с начала 2024 года по сегодня)
    params = {
        "dateFrom": "2024-01-01",
        "dateTo": "2025-02-01" 
    }
    
    headers = {
        "Authorization": TOKEN
    }
    
    try:
        # Шаг 1. Запрос
        print(f"📡 Запрос к: {url}")
        r = requests.get(url, params=params, headers=headers, timeout=60)
        
        print(f"📩 Статус: {r.status_code}")
        
        if r.status_code == 200:
            data = r.json()
            # Это список строк отчета
            if data:
                print(f"✅ УРА! Найдено финансовых записей: {len(data)}")
                print("Пример первой записи (за что деньги):")
                first_row = data[0]
                print(f" - Товар: {first_row.get('sa_name')} ({first_row.get('ts_name')})")
                print(f" - Артикул: {first_row.get('sa_nm')}")
                print(f" - Тип операции: {first_row.get('supplier_oper_name')}")
                print(f" - Сумма: {first_row.get('retail_amount')} руб.")
            else:
                print("⚠️ Отчет сформировался успешно, но он ПУСТОЙ. WB утверждает, что денег не было.")
                
        elif r.status_code == 429:
            print("⏳ Слишком часто. Подождите минуту.")
        else:
            print(f"❌ Ошибка: {r.text[:300]}")
            
    except Exception as e:
        print(f"💥 Ошибка: {e}")

if __name__ == "__main__":
    check_financial_report()