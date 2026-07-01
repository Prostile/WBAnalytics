import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import requests

logger = logging.getLogger(__name__)


class WBClient:
    """Минимальный клиент WB API.

    Важно: финансовый отчет загружается через новый finance/v1 API.
    Старый /api/v5/supplier/reportDetailByPeriod оставлен только как fallback.
    """

    FINANCE_FIELDS = [
        "realizationReportId",
        "rrdId",
        "subjectName",
        "nmId",
        "brandName",
        "saName",
        "barcode",
        "srid",
        "dateFrom",
        "dateTo",
        "createDt",
        "orderDt",
        "saleDt",
        "rrDt",
        "docTypeName",
        "supplierOperName",
        "quantity",
        "retailPrice",
        "retailAmount",
        "retailPriceWithdiscRub",
        "salePercent",
        "commissionPercent",
        "ppvzSalesCommission",
        "ppvzForPay",
        "forPay",
        "ppvzReward",
        "acquiringFee",
        "acquiringPercent",
        "deliveryAmount",
        "returnAmount",
        "deliveryRub",
        "deliveryService",
        "rebillLogisticCost",
        "storageFee",
        "paidStorage",
        "deduction",
        "acceptance",
        "paidAcceptance",
        "penalty",
        "additionalPayment",
        "supplierPromo",
        "productDiscountForReport",
        "sellerPromoDiscount",
        "loyaltyDiscount",
        "cashbackAmount",
        "cashbackDiscount",
        "wibesWbDiscountPercent",
        "salePricePromocodeDiscountPrc",
        "salePriceWholesaleDiscountPrc",
        "officeName",
        "warehouseName",
        "siteCountry",
        "deliveryMethod",
    ]

    def __init__(self):
        self.token = os.getenv("WB_API_TOKEN")
        self.headers = {
            "Authorization": self.token or "",
            "Content-Type": "application/json",
        }

    def _make_request(self, method: str, url: str, **kwargs):
        retries = 3
        for attempt in range(retries):
            try:
                response = requests.request(method, url, headers=self.headers, timeout=90, **kwargs)

                if response.status_code == 204:
                    return None
                if response.status_code in {200, 201}:
                    if not response.text:
                        return {}
                    return response.json()
                if response.status_code == 429:
                    wait_time = int(response.headers.get("X-Ratelimit-Retry", 60))
                    logger.warning("WB 429. Retry in %s sec", wait_time)
                    time.sleep(wait_time)
                    continue
                if response.status_code == 401:
                    raise RuntimeError("WB API token is invalid or expired")

                response.raise_for_status()
            except requests.exceptions.RequestException as exc:
                logger.exception("WB network error: %s", exc)
                if attempt == retries - 1:
                    raise
                time.sleep(5)
        return []

    def get_cards(self):
        url = "https://content-api.wildberries.ru/content/v2/get/cards/list"
        payload = {"settings": {"cursor": {"limit": 100}, "filter": {"withPhoto": -1}}}
        data = self._make_request("POST", url, json=payload)

        if isinstance(data, dict):
            raw_cards = data.get("cards", [])
            cleaned = []
            for card in raw_cards:
                photos = card.get("photos", [])
                title = card.get("title") or ""
                if not title:
                    brand = card.get("brand", "")
                    subject = card.get("subjectName", "Товар")
                    title = f"{subject} {brand}".strip()

                cleaned.append(
                    {
                        "nm_id": card.get("nmID"),
                        "vendor_code": card.get("vendorCode"),
                        "name": title,
                        "photo_url": photos[0].get("big") if photos else None,
                    }
                )
            return cleaned
        return []

    def get_financial_report(self, date_from: str, date_to: str) -> List[dict]:
        """Загружает детализированный финансовый отчет через новый finance/v1 API.

        Пагинация идет по rrdId. Если новый метод недоступен, используется legacy fallback.
        """

        try:
            return self.get_financial_report_v1(date_from, date_to)
        except Exception as exc:
            logger.warning("finance/v1 report failed, fallback to v5: %s", exc)
            return self.get_financial_report_legacy(date_from, date_to)

    def get_financial_report_v1(self, date_from: str, date_to: str) -> List[dict]:
        url = "https://statistics-api.wildberries.ru/api/finance/v1/sales-reports/detailed"
        all_rows: List[dict] = []
        rrd_id = 0

        while True:
            payload = {
                "dateFrom": date_from,
                "dateTo": date_to,
                "limit": 100000,
                "rrdId": rrd_id,
                "period": "daily",
                "fields": self.FINANCE_FIELDS,
            }
            print(f"💰 Запрос финансов finance/v1: {date_from} — {date_to}, rrdId={rrd_id}")
            chunk = self._make_request("POST", url, json=payload)

            if chunk is None:
                break
            if isinstance(chunk, dict):
                rows = chunk.get("data") or chunk.get("rows") or chunk.get("report") or []
            elif isinstance(chunk, list):
                rows = chunk
            else:
                rows = []

            if not rows:
                break

            all_rows.extend(rows)
            next_rrd_id = self._extract_last_rrd_id(rows)
            if not next_rrd_id or next_rrd_id == rrd_id:
                break
            rrd_id = next_rrd_id

            # защита от случайного бесконечного цикла
            if len(rows) < 100000:
                break

        return all_rows

    def get_financial_report_legacy(self, date_from: str, date_to: str) -> List[dict]:
        url = "https://statistics-api.wildberries.ru/api/v5/supplier/reportDetailByPeriod"
        all_rows: List[dict] = []
        rrd_id = 0

        while True:
            params = {"dateFrom": date_from, "dateTo": date_to, "rrdid": rrd_id, "limit": 100000}
            print(f"💰 Legacy V5 finance: {date_from} — {date_to}, rrdid={rrd_id}")
            chunk = self._make_request("GET", url, params=params)
            if chunk is None:
                break
            rows = chunk if isinstance(chunk, list) else []
            if not rows:
                break
            all_rows.extend(rows)
            next_rrd_id = self._extract_last_rrd_id(rows)
            if not next_rrd_id or next_rrd_id == rrd_id:
                break
            rrd_id = next_rrd_id
            if len(rows) < 100000:
                break

        return all_rows

    @staticmethod
    def _extract_last_rrd_id(rows: Iterable[dict]) -> Optional[int]:
        last_id = None
        for row in rows:
            value = row.get("rrdId", row.get("rrd_id"))
            try:
                if value is not None:
                    last_id = int(value)
            except (TypeError, ValueError):
                continue
        return last_id

    def get_prices(self):
        url = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"
        price_map: Dict[int, Dict[str, float | int]] = {}
        offset = 0
        limit = 1000

        while True:
            data = self._make_request("GET", url, params={"limit": limit, "offset": offset, "filterPrice": -1})
            if not isinstance(data, dict):
                break
            goods = data.get("data", {}).get("listGoods", [])
            if not goods:
                break
            for good in goods:
                sizes = good.get("sizes", [])
                base = sizes[0].get("price", 0) if sizes else 0
                disc = good.get("discount", 0)
                nm_id = good.get("nmID")
                if nm_id is None:
                    continue
                price_map[int(nm_id)] = {
                    "wb_price_base": float(base or 0),
                    "wb_discount": int(disc or 0),
                    "wb_price_final": float(base or 0) * (1 - int(disc or 0) / 100),
                }
            if len(goods) < limit:
                break
            offset += limit

        return price_map

    def get_orders(self, date_from: str):
        url = "https://statistics-api.wildberries.ru/api/v1/supplier/orders"
        data = self._make_request(
            "GET",
            url,
            params={"dateFrom": date_from if "T" in date_from else f"{date_from}T00:00:00", "flag": 0},
        )
        if data:
            return data

        all_orders = []
        from datetime import datetime, timedelta

        end_date = datetime.now()
        start_date = end_date - timedelta(days=45)
        current_start = start_date
        while current_start < end_date:
            d_from = current_start.strftime("%Y-%m-%dT00:00:00")
            chunk = self._make_request("GET", url, params={"dateFrom": d_from, "flag": 0})
            if chunk:
                all_orders.extend(chunk)
            current_start += timedelta(days=15)
            time.sleep(1)
        return all_orders

    def get_sales(self, date_from: str):
        url = "https://statistics-api.wildberries.ru/api/v1/supplier/sales"
        data = self._make_request(
            "GET",
            url,
            params={"dateFrom": date_from if "T" in date_from else f"{date_from}T00:00:00", "flag": 0},
        )
        if data:
            return data

        all_sales = []
        from datetime import datetime, timedelta

        end_date = datetime.now()
        start_date = end_date - timedelta(days=60)
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
        """Создает WB upload task для цен и скидок.

        Возвращает словарь с признаком принятия задачи. Финальное применение нужно
        проверять отдельно через status endpoint.
        """

        if not updates:
            return {"accepted": False, "message": "empty payload"}

        url = "https://discounts-prices-api.wildberries.ru/api/v2/upload/task"
        payload = {"data": updates}
        print(f"📤 Создаем задачу WB price upload: {len(updates)} товаров")
        data = self._make_request("POST", url, json=payload)
        upload_id = None
        if isinstance(data, dict):
            upload_id = (
                data.get("data", {}).get("id")
                or data.get("data", {}).get("uploadID")
                or data.get("id")
                or data.get("uploadID")
            )
        return {"accepted": True, "upload_id": upload_id, "raw": data}

    def get_price_upload_status(self, upload_id: str | int):
        url = "https://discounts-prices-api.wildberries.ru/api/v2/history/tasks"
        return self._make_request("GET", url, params={"uploadID": upload_id})


wb = WBClient()
