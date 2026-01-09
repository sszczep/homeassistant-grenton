from __future__ import annotations

from .base import GrentonCluApiRequest, GrentonCluApiResponse


class GrentonCluApiPingRequest(GrentonCluApiRequest):
    """Ping request to check if CLU is alive."""
    
    def __init__(self, msg_id: str | None = None):
        super().__init__("checkAlive()", msg_id)


class GrentonCluApiPingResponse(GrentonCluApiResponse):
    """Ping response from CLU."""

    def __init__(self, wire_message: str):
        """Initialize from wire format message."""
        super().__init__(wire_message)
