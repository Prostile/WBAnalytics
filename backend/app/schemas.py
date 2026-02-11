from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime

# Базовая схема (общие поля)
class ItemBase(BaseModel):
    nm_id: int
    vendor_code: Optional[str] = None
    name: Optional[str] = None
    photo_url: Optional[str] = None
    
    # ЭКОНОМИКА (Этих полей не хватало!)
    cost_price: float = 0.0
    target_profit: float = 0.0
    min_price: float = 0.0
    
    # НАСТРОЙКИ
    tax_rate: float = 0.06
    wb_commission: float = 0.26
    logistics_cost: float = 50.0
    
    # СТАТУСЫ
    wb_price_base: float = 0.0
    wb_discount: int = 0
    wb_price_final: float = 0.0
    
    repricer_mode: str = "manual"
    is_active: bool = True

# То, что мы получаем при создании/обновлении
class ItemCreate(ItemBase):
    pass

# То, что мы отдаем на сайт (добавляем id и updated_at)
class Item(ItemBase):
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True # Важно для работы с SQLAlchemy

# Схемы для аналитики
class AnalyticsRequest(BaseModel):
    days: int = 30

class SyncRequest(BaseModel):
    days: int = 30

# Схема для массового обновления цен
class PriceUpdateReq(BaseModel):
    nm_id: int
    new_price: int