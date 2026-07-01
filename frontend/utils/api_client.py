import os
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8111")


class APIClient:
    """Класс для взаимодействия с backend через REST API."""

    @staticmethod
    def _get(endpoint: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Any:
        try:
            response = requests.get(f"{BACKEND_URL}{endpoint}", params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            st.error(f"⚠️ Ошибка API (GET {endpoint}): {exc}")
            return None

    @staticmethod
    def _post(
        endpoint: str,
        json_data: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 90,
    ) -> Any:
        try:
            response = requests.post(f"{BACKEND_URL}{endpoint}", json=json_data, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            st.error(f"⚠️ Ошибка API (POST {endpoint}): {exc}")
            return None

    @classmethod
    def get_items(cls) -> List[Dict[str, Any]]:
        return cls._get("/items/") or []

    @classmethod
    def save_item(cls, item_data: Dict[str, Any]) -> bool:
        return cls._post("/items/", json_data=item_data) is not None

    @classmethod
    def bulk_save_items(cls, items_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        return cls._post("/items/bulk_upsert", json_data=items_data, timeout=120) or {}

    @classmethod
    def import_from_wb(cls) -> bool:
        return cls._post("/items/import_from_wb", timeout=120) is not None

    @classmethod
    def get_repricer_status(cls) -> List[Dict[str, Any]]:
        return cls._get("/repricer/status") or []

    @classmethod
    def batch_update_prices(cls, updates: List[Dict[str, int]], source: str = "manual_ui") -> bool:
        return cls._post("/repricer/batch_update", json_data=updates, params={"source": source}) is not None

    @classmethod
    def get_automation_status(cls) -> Dict[str, Any]:
        return cls._get("/repricer/automation_status") or {}

    @classmethod
    def get_repricer_history(cls, limit: int = 20) -> Dict[str, Any]:
        return cls._get("/repricer/history", params={"limit": limit}) or {"events": []}

    @classmethod
    def run_auto_now(cls) -> Dict[str, Any]:
        return cls._post("/repricer/run_auto_now", timeout=180) or {}

    @classmethod
    def sync_finance(cls, days: int = 90) -> Dict[str, Any]:
        return cls._post("/analytics/sync_finance", json_data={"days": days}, timeout=180) or {}

    @classmethod
    def get_finance_dashboard(cls) -> Dict[str, Any]:
        return cls._get("/analytics/finance_dashboard", timeout=60) or {}

    @classmethod
    def get_analytics_summary(cls, days: int = 30) -> Dict[str, Any]:
        return cls._get("/analytics/summary", params={"days": days}, timeout=60) or {}

    @classmethod
    def get_unit_economics(cls, days: int = 30) -> List[Dict[str, Any]]:
        payload = cls._get("/analytics/unit-economics", params={"days": days}, timeout=60) or {}
        return payload.get("items", [])

    @classmethod
    def get_timeseries(cls, days: int = 30) -> List[Dict[str, Any]]:
        payload = cls._get("/analytics/timeseries", params={"days": days}, timeout=60) or {}
        return payload.get("points", [])

    @classmethod
    def get_pnl(cls, days: int = 30) -> List[Dict[str, Any]]:
        payload = cls._get("/analytics/pnl", params={"days": days}, timeout=60) or {}
        return payload.get("items", [])

    @classmethod
    def get_recommendations(cls, days: int = 30) -> List[Dict[str, Any]]:
        payload = cls._get("/recommendations", params={"days": days}, timeout=60) or {}
        return payload.get("recommendations", [])
