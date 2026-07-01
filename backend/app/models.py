from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from .database import Base


class Item(Base):
    __tablename__ = "items"

    nm_id = Column(Integer, primary_key=True, index=True)
    vendor_code = Column(String, nullable=True)
    name = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)

    # --- ЭКОНОМИКА ТОВАРА ---
    cost_price = Column(Float, default=0.0)
    target_profit = Column(Float, default=0.0)  # legacy: больше не управляет автоценой
    desired_profit_rub = Column(Float, default=0.0)
    min_profit_rub = Column(Float, default=0.0)
    min_price = Column(Float, default=0.0)  # legacy price floor

    tax_rate = Column(Float, default=0.06)
    wb_commission = Column(Float, default=0.26)
    logistics_cost = Column(Float, default=50.0)
    return_cost_per_unit = Column(Float, default=0.0)
    ads_cost_per_unit = Column(Float, default=0.0)
    overhead_per_unit = Column(Float, default=0.0)

    # --- ДАННЫЕ С WB ---
    wb_price_base = Column(Float, default=0.0)
    wb_discount = Column(Integer, default=0)
    wb_price_final = Column(Float, default=0.0)

    # --- PRICE LOCK: единственный автоматический режим изменения цены ---
    price_lock_enabled = Column(Boolean, default=False)
    locked_final_price = Column(Float, default=0.0)
    locked_discount = Column(Integer, nullable=True)
    price_tolerance_rub = Column(Float, default=50.0)
    pricing_strategy = Column(String, default="fixed_final_price")

    # --- LEGACY / РУЧНОЙ РЕКОМЕНДАТЕЛЬНЫЙ КОНТУР ---
    target_discount = Column(Integer, nullable=True)
    max_price = Column(Float, default=0.0)
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
    source = Column(String, default="manual_ui")
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"

    srid = Column(String, primary_key=True, index=True)
    nm_id = Column(Integer, ForeignKey("items.nm_id"))
    total_price = Column(Float)
    warehouse_name = Column(String)
    oblast_okrug_name = Column(String)
    income_id = Column(Integer)
    is_cancel = Column(Boolean, default=False)
    date = Column(DateTime(timezone=True))


class Sale(Base):
    __tablename__ = "sales"

    sale_id = Column(String, primary_key=True, index=True)
    srid = Column(String, ForeignKey("orders.srid"), nullable=True)
    nm_id = Column(Integer, ForeignKey("items.nm_id"))
    price_with_disc = Column(Float)
    for_pay = Column(Float)
    finished_price = Column(Float)
    region_name = Column(String)
    date = Column(DateTime(timezone=True))


class FinanceRawRow(Base):
    """Сырая строка финансового отчета WB.

    Нужна, чтобы не терять поля при изменениях API и иметь возможность
    перепарсить аналитику без повторной загрузки отчета из WB.
    """

    __tablename__ = "wb_finance_raw_rows"

    id = Column(Integer, primary_key=True, index=True)
    source_api_version = Column(String, default="finance_v1")
    report_id = Column(BigInteger, nullable=True)
    rrd_id = Column(BigInteger, index=True, nullable=True)
    nm_id = Column(Integer, index=True, nullable=True)
    srid = Column(String, nullable=True)
    raw_json = Column(JSON)
    imported_at = Column(DateTime(timezone=True), server_default=func.now())


class FinanceRecord(Base):
    __tablename__ = "finance_records"

    rrd_id = Column(BigInteger, primary_key=True, index=True)
    report_id = Column(BigInteger)
    nm_id = Column(Integer, nullable=True, index=True)
    srid = Column(String, nullable=True)
    vendor_code = Column(String, nullable=True)
    barcode = Column(String, nullable=True)
    subject_name = Column(String, nullable=True)
    brand_name = Column(String, nullable=True)

    date_from = Column(DateTime)
    date_to = Column(DateTime)
    order_dt = Column(DateTime, nullable=True)
    sale_dt = Column(DateTime, nullable=True)
    rr_dt = Column(DateTime, nullable=True)

    oper_type = Column(String)
    doc_type_name = Column(String, nullable=True)
    quantity = Column(Float, default=1.0)

    retail_price = Column(Float, default=0.0)
    retail_amount = Column(Float, default=0.0)
    retail_price_withdisc_rub = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)  # ppvz_for_pay / forPay

    commission_percent = Column(Float, default=0.0)
    ppvz_sales_commission = Column(Float, default=0.0)
    ppvz_reward = Column(Float, default=0.0)
    acquiring_fee = Column(Float, default=0.0)
    acquiring_percent = Column(Float, default=0.0)

    delivery_amount = Column(Float, default=0.0)
    return_amount = Column(Float, default=0.0)
    delivery_rub = Column(Float, default=0.0)
    delivery_service = Column(Float, default=0.0)
    rebill_logistic_cost = Column(Float, default=0.0)

    storage_fee = Column(Float, default=0.0)
    deduction = Column(Float, default=0.0)
    acceptance = Column(Float, default=0.0)
    penalty = Column(Float, default=0.0)
    additional_payment = Column(Float, default=0.0)

    supplier_promo = Column(Float, default=0.0)
    product_discount_for_report = Column(Float, default=0.0)
    seller_promo_discount = Column(Float, default=0.0)
    loyalty_discount = Column(Float, default=0.0)
    cashback_amount = Column(Float, default=0.0)
    cashback_discount = Column(Float, default=0.0)
    wibes_wb_discount_percent = Column(Float, default=0.0)
    sale_price_promocode_discount_prc = Column(Float, default=0.0)
    sale_price_wholesale_discount_prc = Column(Float, default=0.0)

    warehouse_name = Column(String, nullable=True)
    office_name = Column(String, nullable=True)
    site_country = Column(String, nullable=True)
    delivery_method = Column(String, nullable=True)
    raw_json = Column(JSON, nullable=True)
    imported_at = Column(DateTime(timezone=True), server_default=func.now())


class PriceRecommendation(Base):
    __tablename__ = "price_recommendations"

    id = Column(Integer, primary_key=True, index=True)
    nm_id = Column(Integer, ForeignKey("items.nm_id"), index=True)
    period_from = Column(DateTime, nullable=True)
    period_to = Column(DateTime, nullable=True)
    current_final_price = Column(Float, default=0.0)
    locked_final_price = Column(Float, default=0.0)
    recommended_final_price = Column(Float, default=0.0)
    recommended_base_price = Column(Float, default=0.0)
    recommended_discount = Column(Integer, default=0)
    current_profit_per_unit = Column(Float, default=0.0)
    projected_profit_per_unit = Column(Float, default=0.0)
    min_viable_price = Column(Float, default=0.0)
    reason_code = Column(String, nullable=True)
    reason_text = Column(String, nullable=True)
    severity = Column(String, default="info")
    confidence = Column(String, default="medium")
    status = Column(String, default="new")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    applied_at = Column(DateTime(timezone=True), nullable=True)


class WbPriceUploadTask(Base):
    __tablename__ = "wb_price_upload_tasks"

    id = Column(Integer, primary_key=True, index=True)
    upload_id = Column(String, nullable=True, index=True)
    source = Column(String, default="price_lock")
    status = Column(String, default="created")
    payload_json = Column(JSON, nullable=True)
    response_json = Column(JSON, nullable=True)
    error_text = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    checked_at = Column(DateTime(timezone=True), nullable=True)


class RepricerRun(Base):
    __tablename__ = "repricer_runs"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, default="scheduler_price_lock")
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
    old_discount = Column(Integer, default=0)
    new_discount = Column(Integer, default=0)
    price_delta = Column(Float, default=0.0)
    price_delta_percent = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
