"""WebSocket URI helper shared by the network clients."""

from __future__ import annotations


def ws_uri(host: str, port: int, *, tls: bool) -> str:
    """Build the client connection URI.

    ``tls=True`` uses the ``wss`` scheme (e.g. behind a TLS reverse
    proxy on port 443); otherwise plain ``ws``.
    """
    scheme = "wss" if tls else "ws"
    return f"{scheme}://{host}:{port}"
