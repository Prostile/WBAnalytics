from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ItemBase(BaseModel):
    nm_id: int
    vendor_code: Optional[str] = None
    name: Optional[str] = None
    photo_url: Optional[str] = None

    cost_price: float = 0.0
    target_profit: float = 0.0
    desired_profit_rub: float = 0.0
    min_profit_rub: float = 0.0
    min_price: float = 0.0

    tax_rate: float = 0.06
    wb_commission: float = 0.26
    logistics_cost: float = 50.0
    return_cost_per_unit: float = 0.0
    ads_cost_per_unit: float = 0.0
    overhead_per_unit: float = 0.0

    wb_price_base: float = 0.0
    wb_discount: int = 0
    wb_price_final: float = 0.0

    price_lock_enabled: bool = False
    locked_final_price: float = 0.0
    locked_discount: Optional[int] = None
    price_tolerance_rub: float = 50.0
    pricing_strategy: str = "fixed_final_price"

    target_discount: Optional[int] = None
    max_price: float = 0.0
    repricer_mode: str = "manual"
    is_active: bool = True


class ItemCreate(ItemBase):
    pass


class Item(ItemBase):
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AnalyticsRequest(BaseModel):
    days: int = 30


class SyncRequest(BaseModel):
    days: int = 30


class PriceUpdateReq(BaseModel):
    nm_id: int
    new_price: int
    new_discount: Optional[int] = None


class BulkItemsUpsertResult(BaseModel):
    status: str = "success"
    total: int
    created: int
    updated: int


class AnalyticsFilters(BaseModel):
    days: int = 30
    nm_ids: Optional[List[int]] = None
    warehouses: Optional[List[str]] = None
    operation_types: Optional[List[str]] = None


class PriceRecommendationOut(BaseModel):
    nm_id: int
    name: Optional[str] = None
    current_final_price: float
    locked_final_price: float
    recommended_final_price: float
    recommended_base_price: float
    recommended_discount: int
    current_profit_per_unit: float
    projected_profit_per_unit: float
    min_viable_price: float
    reason_code: str
    reason_text: str
    severity: str
    confidence: str = "medium"


class AnalyticsResponse(BaseModel):
    summary: Dict[str, Any]
    pnl: List[Dict[str, Any]]
    timeseries: List[Dict[str, Any]]
    unit_economics: List[Dict[str, Any]]
    recommendations: List[Dict[str, Any]]
