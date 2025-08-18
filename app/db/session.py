from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings


def get_async_engine():
    return create_async_engine(settings.db_url, echo=False, future=True)


def get_async_session_maker():
    engine = get_async_engine()
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
