from pydantic import BaseModel
from datetime import datetime
from typing import Optional

# Базовая схема товара
class ItemBase(BaseModel):
    nm_id: int
    vendor_code: Optional[str] = None
    name: Optional[str] = None
    photo_url: Optional[str] = None
    
    # Экономика (Наши настройки)
    cost_price: float = 0.0
    target_profit: float = 0.0
    min_price: float = 0.0
    
    # --- НОВЫЕ ПОЛЯ (Цены с WB) ---
    wb_price_base: float = 0.0
    wb_discount: int = 0
    wb_price_final: float = 0.0
    
    repricer_active: bool = False

# Схема для создания (что присылает сайт)
class ItemCreate(ItemBase):
    pass

# Схема для чтения (что отдает API)
class Item(ItemBase):
    is_active: bool
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class SyncRequest(BaseModel):
    days: int = 30

# Создадим простую модель для приема запроса
class PriceUpdateReq(BaseModel):
    nm_id: int
    new_price: int # Розничная цена