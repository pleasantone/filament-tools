"""Local-only editor binding and request boundary."""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit


def is_loopback_host(value: str) -> bool:
    host = value.strip().casefold()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_editor_host(host: str) -> str:
    value = host.strip()
    if not is_loopback_host(value):
        raise ValueError(
            "the editor contains local file and installation APIs and may only bind to "
            "localhost or a loopback IP address"
        )
    return value


def _header_host(value: str) -> str:
    return urlsplit(f"//{value}").hostname or ""


def _origin_host(value: str) -> str:
    return urlsplit(value).hostname or ""


class LocalEditorBoundary:
    """Reject DNS-rebinding and cross-origin browser access to the local editor."""

    def __init__(self, app: Callable[..., Awaitable[Any]]):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").casefold(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        host_allowed = is_loopback_host(_header_host(headers.get("host", "")))
        origin = headers.get("origin")
        origin_allowed = not origin or is_loopback_host(_origin_host(origin))
        if host_allowed and origin_allowed:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"detail":"local editor access denied"}',
            }
        )
