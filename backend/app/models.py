from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, BigInteger
from sqlalchemy.sql import func
from .database import Base

class Item(Base):
    __tablename__ = "items"

    nm_id = Column(Integer, primary_key=True, index=True)
    vendor_code = Column(String, nullable=True)
    name = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)
    
    # --- ЭКОНОМИКА (INPUTS - Вводите вы) ---
    cost_price = Column(Float, default=0.0)      # Себестоимость товара
    target_profit = Column(Float, default=0.0)   # Сколько ХОЧУ зарабатывать (руб)
    min_price = Column(Float, default=0.0)       # Минимальная цена (чтобы не уйти в минус)
    
    # --- НАСТРОЙКИ РАСЧЕТА (INPUTS - Вводите вы или берем среднее) ---
    tax_rate = Column(Float, default=0.06)       # Налог (0.07 = 7%)
    wb_commission = Column(Float, default=0.26)  # Комиссия WB (0.25 = 25%)
    logistics_cost = Column(Float, default=50.0) # Логистика на 1 шт (базовая)
    
    # --- ДАННЫЕ С WB (LIVE) ---
    wb_price_base = Column(Float, default=0.0)   # Розничная (зачеркнутая)
    wb_discount = Column(Integer, default=0)     # Скидка продавца %
    wb_price_final = Column(Float, default=0.0)  # Текущая цена на сайте
    
    # --- УПРАВЛЕНИЕ ---
    # Режим работы: 'manual' (только советы) или 'auto' (сам меняет цены)
    repricer_mode = Column(String, default="manual") 
    is_active = Column(Boolean, default=True)
    
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class PriceHistory(Base):
    __tablename__ = "price_history"
    id = Column(Integer, primary_key=True, index=True)
    nm_id = Column(Integer, ForeignKey("items.nm_id"))
    price_retail = Column(Float)
    discount = Column(Integer)
    final_price = Column(Float)
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())

# ... (код Item и PriceHistory остается выше)

class Order(Base):
    __tablename__ = "orders"

    srid = Column(String, primary_key=True, index=True) # Уникальный ID заказа WB
    nm_id = Column(Integer, ForeignKey("items.nm_id"))
    total_price = Column(Float)       # Цена, по которой заказали
    warehouse_name = Column(String)   # Склад отгрузки
    oblast_okrug_name = Column(String) # Регион доставки (для карты)
    income_id = Column(Integer)       # Номер поставки (если FBO)
    is_cancel = Column(Boolean, default=False) # Была ли отмена
    date = Column(DateTime(timezone=True))     # Время заказа
    
    # Связь с товаром
    # item = relationship("Item") # (Опционально, если нужны join-ы)

class Sale(Base):
    __tablename__ = "sales"

    sale_id = Column(String, primary_key=True, index=True)
    srid = Column(String, ForeignKey("orders.srid"), nullable=True) # Связь с заказом
    nm_id = Column(Integer, ForeignKey("items.nm_id"))
    price_with_disc = Column(Float)   # Цена реализации
    for_pay = Column(Float)           # К перечислению (Выручка)
    finished_price = Column(Float)    # Фактическая цена
    region_name = Column(String)
    date = Column(DateTime(timezone=True))

class FinanceRecord(Base):
    __tablename__ = "finance_records"

    rrd_id = Column(BigInteger, primary_key=True, index=True)
    report_id = Column(BigInteger)
    nm_id = Column(Integer, nullable=True)
    
    date_from = Column(DateTime)
    date_to = Column(DateTime)
    
    oper_type = Column(String)
    retail_amount = Column(Float)   # Цена розничная (сколько заплатил покупатель)
    amount = Column(Float)          # К перечислению (ppvz_for_pay)
    delivery_rub = Column(Float)    # Логистика
    
    # --- НОВЫЕ ПОЛЯ ---
    penalty = Column(Float, default=0.0)      # Штрафы
    additional_payment = Column(Float, default=0.0) # Доплаты
    commission_percent = Column(Float, default=0.0) # Процент комиссии
    warehouse_name = Column(String, nullable=True)  # Склад (чтобы знать, откуда едет)
    
    order_dt = Column(DateTime, nullable=True)
    sale_dt = Column(DateTime, nullable=True)


class RepricerRun(Base):
    __tablename__ = "repricer_runs"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, default="scheduler_hourly")
    status = Column(String, default="running")
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)
    checked_items = Column(Integer, default=0)
    eligible_items = Column(Integer, default=0)
    changed_items = Column(Integer, default=0)
    skipped_items = Column(Integer, default=0)
    manual_items = Column(Integer, default=0)
    price_sync_items = Column(Integer, default=0)
    error_message = Column(String, nullable=True)


class RepricerEvent(Base):
    __tablename__ = "repricer_events"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("repricer_runs.id"), nullable=True)
    nm_id = Column(Integer, ForeignKey("items.nm_id"))
    item_name = Column(String, nullable=True)
    source = Column(String, default="manual_ui")
    reason = Column(String, nullable=True)
    old_price_retail = Column(Float, default=0.0)
    new_price_retail = Column(Float, default=0.0)
    old_price_final = Column(Float, default=0.0)
    new_price_final = Column(Float, default=0.0)
    old_profit = Column(Float, default=0.0)
    new_profit = Column(Float, default=0.0)
    target_profit = Column(Float, default=0.0)
    wb_discount = Column(Integer, default=0)
    price_delta = Column(Float, default=0.0)
    price_delta_percent = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
