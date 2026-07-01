from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import text
import os

DATABASE_URL = f"postgresql+asyncpg://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}/{os.getenv('POSTGRES_DB')}"

engine = create_async_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


ITEM_COLUMNS = [
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS target_discount INTEGER",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS max_price DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS desired_profit_rub DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS min_profit_rub DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS return_cost_per_unit DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS ads_cost_per_unit DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS overhead_per_unit DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS price_lock_enabled BOOLEAN DEFAULT FALSE",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS locked_final_price DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS locked_discount INTEGER",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS price_tolerance_rub DOUBLE PRECISION DEFAULT 50",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS pricing_strategy VARCHAR DEFAULT 'fixed_final_price'",
    "UPDATE items SET target_discount = COALESCE(target_discount, wb_discount, 0)",
    "UPDATE items SET locked_discount = COALESCE(locked_discount, target_discount, wb_discount, 0)",
    "UPDATE items SET locked_final_price = COALESCE(NULLIF(locked_final_price, 0), wb_price_final, 0)",
    "UPDATE items SET price_tolerance_rub = COALESCE(price_tolerance_rub, 50)",
    "UPDATE items SET desired_profit_rub = COALESCE(NULLIF(desired_profit_rub, 0), target_profit, 0)",
    "UPDATE items SET min_profit_rub = COALESCE(min_profit_rub, 0)",
]

FINANCE_COLUMNS = [
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS srid VARCHAR",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS vendor_code VARCHAR",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS barcode VARCHAR",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS subject_name VARCHAR",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS brand_name VARCHAR",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS rr_dt TIMESTAMP",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS doc_type_name VARCHAR",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS quantity DOUBLE PRECISION DEFAULT 1",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS retail_price DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS retail_price_withdisc_rub DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS ppvz_sales_commission DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS ppvz_reward DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS acquiring_fee DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS acquiring_percent DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS delivery_amount DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS return_amount DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS delivery_service DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS rebill_logistic_cost DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS storage_fee DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS deduction DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS acceptance DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS supplier_promo DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS product_discount_for_report DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS seller_promo_discount DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS loyalty_discount DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS cashback_amount DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS cashback_discount DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS wibes_wb_discount_percent DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS sale_price_promocode_discount_prc DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS sale_price_wholesale_discount_prc DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS office_name VARCHAR",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS site_country VARCHAR",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS delivery_method VARCHAR",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS raw_json JSONB",
    "ALTER TABLE finance_records ADD COLUMN IF NOT EXISTS imported_at TIMESTAMP WITH TIME ZONE DEFAULT now()",
]

OTHER_COLUMNS = [
    "ALTER TABLE repricer_events ADD COLUMN IF NOT EXISTS old_discount INTEGER DEFAULT 0",
    "ALTER TABLE repricer_events ADD COLUMN IF NOT EXISTS new_discount INTEGER DEFAULT 0",
    "ALTER TABLE price_history ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'manual_ui'",
]


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for statement in ITEM_COLUMNS + FINANCE_COLUMNS + OTHER_COLUMNS:
            await conn.execute(text(statement))


async def get_db():
    async with SessionLocal() as session:
        yield session
