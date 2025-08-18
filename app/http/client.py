from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import httpx


class HttpClient:
    def __init__(self, base_url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.headers = headers or {}
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "HttpClient":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        await self.close()

    async def open(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=self.timeout)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(self, path: str, params: Dict[str, Any] | None = None, headers: Dict[str, str] | None = None) -> httpx.Response:
        assert self._client is not None
        return await self._client.get(path, params=params, headers=headers)

    async def post(self, path: str, data: Dict[str, Any] | None = None, headers: Dict[str, str] | None = None) -> httpx.Response:
        assert self._client is not None
        return await self._client.post(path, data=data, headers=headers)
