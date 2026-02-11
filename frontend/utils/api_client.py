import os
import requests
from typing import List, Dict, Any, Optional
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8111")

class APIClient:
    """Класс для взаимодействия с Бэкендом через REST API."""
    
    @staticmethod
    def _get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        try:
            response = requests.get(f"{BACKEND_URL}{endpoint}", params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            st.error(f"⚠️ Ошибка API (GET {endpoint}): {e}")
            return None

    @staticmethod
    def _post(endpoint: str, json_data: Optional[Any] = None) -> Any:
        try:
            response = requests.post(f"{BACKEND_URL}{endpoint}", json=json_data, timeout=60)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            st.error(f"⚠️ Ошибка API (POST {endpoint}): {e}")
            return None

    # --- ITEMS (Товары) ---
    @classmethod
    def get_items(cls) -> List[Dict[str, Any]]:
        return cls._get("/items/") or []

    @classmethod
    def save_item(cls, item_data: Dict[str, Any]) -> bool:
        return cls._post("/items/", json_data=item_data) is not None

    @classmethod
    def import_from_wb(cls) -> bool:
        return cls._post("/items/import_from_wb") is not None

    # --- REPRICER (Цены) ---
    @classmethod
    def get_repricer_status(cls) -> List[Dict[str, Any]]:
        return cls._get("/repricer/status") or []

    @classmethod
    def batch_update_prices(cls, updates: List[Dict[str, int]]) -> bool:
        return cls._post("/repricer/batch_update", json_data=updates) is not None

    # --- ANALYTICS (Финансы) ---
    @classmethod
    def sync_finance(cls, days: int = 90) -> Dict[str, Any]:
        return cls._post("/analytics/sync_finance", json_data={"days": days}) or {}

    @classmethod
    def get_finance_dashboard(cls) -> Dict[str, Any]:
        return cls._get("/analytics/finance_dashboard") or {}