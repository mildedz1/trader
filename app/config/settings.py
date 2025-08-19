from __future__ import annotations

from functools import lru_cache
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiKeyConfig(BaseModel):
    api_key: str | None = None
    secret_key: str | None = None
    rsa_private_base64: str | None = None
    rsa_public_base64: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")

    # MEXC spot
    # OKX spot
    okx_spot_api_key: str | None = Field(default=None, alias="OKX_SPOT_API_KEY")
    okx_spot_secret_key: str | None = Field(default=None, alias="OKX_SPOT_SECRET_KEY")
    okx_spot_passphrase: str | None = Field(default=None, alias="OKX_SPOT_PASSPHRASE")
    okx_simulated_trading: bool = Field(default=False, alias="OKX_SIMULATED_TRADING")

    lbank_perp_api_key: str | None = Field(default=None, alias="LBANK_PERP_API_KEY")
    lbank_perp_secret_key: str | None = Field(default=None, alias="LBANK_PERP_SECRET_KEY")
    lbank_perp_rsa_private_base64: str | None = Field(default=None, alias="LBANK_PERP_RSA_PRIVATE_BASE64")
    lbank_perp_rsa_public_base64: str | None = Field(default=None, alias="LBANK_PERP_RSA_PUBLIC_BASE64")

    fernet_key: str = Field(alias="FERNET_KEY")

    db_url: str = Field(default="sqlite+aiosqlite:///./data/app.db", alias="DB_URL")

    admin_telegram_user_ids: str = Field(default="", alias="ADMIN_TELEGRAM_USER_IDS")
    ip_whitelist: str = Field(default="", alias="IP_WHITELIST")

    app_env: str = Field(default="prod", alias="APP_ENV")
    app_timezone: str = Field(default="UTC", alias="APP_TIMEZONE")

    def get_spot_keys(self) -> ApiKeyConfig:
        return ApiKeyConfig(
            api_key=self.okx_spot_api_key,
            secret_key=self.okx_spot_secret_key,
        )

    def get_perp_keys(self) -> ApiKeyConfig:
        return ApiKeyConfig(
            api_key=self.lbank_perp_api_key,
            secret_key=self.lbank_perp_secret_key,
            rsa_private_base64=self.lbank_perp_rsa_private_base64,
            rsa_public_base64=self.lbank_perp_rsa_public_base64,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
