"""Route-registration assertions that survive FastAPI's routing internals.

FastAPI >=0.115 keeps `include_router` routes inside an opaque `_IncludedRouter`
wrapper, so scanning `app.routes` no longer surfaces individual paths/methods.
For HTTP routes the OpenAPI schema is the stable, complete registry. WebSocket
routes are not in OpenAPI, so for those we introspect the source router (whose
own `.routes` ARE visible before inclusion).
"""

from __future__ import annotations

from typing import Any


def registered_paths(app: Any) -> set[str]:
    """All registered HTTP route paths (from the OpenAPI schema)."""
    return set(app.openapi()["paths"].keys())


def route_methods(app: Any, path: str) -> set[str]:
    """Uppercased HTTP methods registered for an exact path."""
    return {m.upper() for m in app.openapi()["paths"].get(path, {})}


def router_paths(router: Any) -> set[str]:
    """Paths declared directly on a router (visible before include_router hides
    them at app level). Use for WebSocket routes, which OpenAPI omits."""
    return {getattr(r, "path", "") for r in getattr(router, "routes", [])}
