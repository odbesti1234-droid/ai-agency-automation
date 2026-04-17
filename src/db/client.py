from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import httpx
from dotenv import load_dotenv

load_dotenv()

_URL = os.environ["SUPABASE_URL"].rstrip("/")
_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
_HEADERS = {
    "apikey": _KEY,
    "Authorization": f"Bearer {_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


class SupabaseClient:
    def __init__(self) -> None:
        self._base = f"{_URL}/rest/v1"
        self._http = httpx.Client(headers=_HEADERS, timeout=30)

    # ------------------------------------------------------------------
    def select(
        self,
        table: str,
        filters: dict[str, Any] | None = None,
        client_id: UUID | str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        params: dict[str, str] = {"limit": str(limit)}
        if client_id:
            params["client_id"] = f"eq.{client_id}"
        if filters:
            for k, v in filters.items():
                params[k] = f"eq.{v}"
        r = self._http.get(f"{self._base}/{table}", params=params)
        r.raise_for_status()
        return r.json()

    def insert(
        self,
        table: str,
        row: dict[str, Any],
    ) -> dict:
        r = self._http.post(f"{self._base}/{table}", json=row)
        r.raise_for_status()
        result = r.json()
        return result[0] if isinstance(result, list) else result

    def update(
        self,
        table: str,
        filters: dict[str, Any],
        patch: dict[str, Any],
        client_id: UUID | str | None = None,
    ) -> list[dict]:
        params: dict[str, str] = {}
        if client_id:
            params["client_id"] = f"eq.{client_id}"
        for k, v in filters.items():
            params[k] = f"eq.{v}"
        r = self._http.patch(f"{self._base}/{table}", params=params, json=patch)
        r.raise_for_status()
        return r.json()

    def delete(
        self,
        table: str,
        filters: dict[str, Any],
        client_id: UUID | str | None = None,
    ) -> list[dict]:
        params: dict[str, str] = {}
        if client_id:
            params["client_id"] = f"eq.{client_id}"
        for k, v in filters.items():
            params[k] = f"eq.{v}"
        r = self._http.delete(f"{self._base}/{table}", params=params)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "SupabaseClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


# 싱글턴 (모듈 레벨에서 재사용)
db = SupabaseClient()
