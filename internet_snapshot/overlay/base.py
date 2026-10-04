"""Connector base class for personal overlays."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from .placement import Group


class ProviderAuthError(Exception):
    """The provider rejected the token (HTTP 401)."""


class ProviderError(Exception):
    """The provider failed in a way that is not the caller's fault."""


@dataclass
class AccountData:
    id: str            # stable provider account id (used in overlay node ids)
    label: str
    meta: dict
    groups: list[Group]
    warnings: list[str] = field(default_factory=list)


class Connector:
    provider: str = ""
    label: str = ""
    anchor: str = ""
    scopes: list[str] = []
    authorize_url: str = ""
    token_url: str = ""
    docs: str = ""

    def spec(self) -> dict:
        return {"provider": self.provider, "label": self.label, "anchor": self.anchor,
                "auth": {"type": "oauth2", "scopes": self.scopes, "authorize_url": self.authorize_url,
                         "token_url": self.token_url},
                "proxy": f"/v1/overlay/{self.provider}", "docs": self.docs}

    async def fetch(self, client: httpx.AsyncClient, token: str, max_assets: int) -> AccountData:
        raise NotImplementedError

    @staticmethod
    def check(resp: httpx.Response) -> httpx.Response:
        if resp.status_code == 401:
            raise ProviderAuthError(f"{resp.request.url.host} rejected the token")
        if resp.status_code >= 500:
            raise ProviderError(f"{resp.request.url.host} returned {resp.status_code}")
        return resp
