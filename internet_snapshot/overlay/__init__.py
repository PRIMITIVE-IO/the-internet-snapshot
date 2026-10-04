"""Personal overlays: the slice of a service that a user controls, attached to that service's node.

Privacy model (docs/DESIGN.md §8.3): this package is stateless. Tokens arrive per request,
are used to call the provider, and are dropped. Nothing is persisted or logged.
"""

from __future__ import annotations

from .base import AccountData, Connector, ProviderAuthError, ProviderError
from .github import GitHubConnector
from .google import GoogleConnector

CONNECTORS: dict[str, Connector] = {c.provider: c for c in (GitHubConnector(), GoogleConnector())}

__all__ = ["CONNECTORS", "AccountData", "Connector", "ProviderAuthError", "ProviderError", "connector_specs"]


def connector_specs() -> list[dict]:
    return [c.spec() for c in CONNECTORS.values()]
