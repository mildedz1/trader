from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text


class Base(DeclarativeBase):
    pass


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(16))  # spot/perp
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    encrypted_secret_key: Mapped[str] = mapped_column(Text)
    encrypted_rsa_private: Mapped[str] = mapped_column(Text, default="")
    encrypted_rsa_public: Mapped[str] = mapped_column(Text, default="")
    ip_whitelist: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[str] = mapped_column(String(32), default="")
