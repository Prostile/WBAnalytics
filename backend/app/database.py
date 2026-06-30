# backend/app/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import text
import os

DATABASE_URL = f"postgresql+asyncpg://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}/{os.getenv('POSTGRES_DB')}"

engine = create_async_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def init_db():
    async with engine.begin() as conn:
        # ВАЖНО: create_all создает только те таблицы, модели которых были импортированы ДО запуска этой функции
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE items ADD COLUMN IF NOT EXISTS target_discount INTEGER"))
        await conn.execute(text("ALTER TABLE items ADD COLUMN IF NOT EXISTS max_price DOUBLE PRECISION DEFAULT 0"))
        await conn.execute(text("UPDATE items SET target_discount = COALESCE(target_discount, wb_discount, 0)"))
        await conn.execute(text("UPDATE items SET max_price = COALESCE(max_price, 0)"))
        await conn.execute(text("ALTER TABLE repricer_events ADD COLUMN IF NOT EXISTS old_discount INTEGER DEFAULT 0"))
        await conn.execute(text("ALTER TABLE repricer_events ADD COLUMN IF NOT EXISTS new_discount INTEGER DEFAULT 0"))

async def get_db():
    async with SessionLocal() as session:
        yield session
