from __future__ import annotations

from ....state import (
    GrentonCluStateVariableKey,
    GrentonCluStateAttributeKey,
    GrentonValue,
    cast_string_to_grenton_value,
)
from .base import GrentonCluApiRequest, GrentonCluApiResponse, GrentonCluApiNotification


def _parse_client_report_payload(payload: str) -> list[GrentonValue]:
    """Parse the clientReport payload into GrentonValue list."""
    if not payload.startswith("clientReport:"):
        return []
    
    report_parts = payload.split(":", 2)
    if len(report_parts) != 3:
        return []
    
    data_payload = report_parts[2]
    
    if not (data_payload.startswith("{") and data_payload.endswith("}")):
        return []
    
    content = data_payload[1:-1].strip()
    if not content:
        return []
    
    raw_values = content.split(",")
    return [cast_string_to_grenton_value(value.strip().strip('"')) for value in raw_values]


class GrentonCluApiClientRegisterRequest(GrentonCluApiRequest):
    """Request to register component states for subscription."""
    
    keys: list[GrentonCluStateVariableKey | GrentonCluStateAttributeKey]
    
    def __init__(self, keys: list[GrentonCluStateVariableKey | GrentonCluStateAttributeKey], msg_id: str | None = None):
        """Initialize with state keys to register."""
        self.keys = keys
        
        if not keys:
            raise ValueError("Cannot create registration request with no keys")
        
        mapped_keys: list[str] = []
        
        for key in keys:
            if isinstance(key, GrentonCluStateVariableKey):
                mapped_keys.append(f'"{key.name}"')
            elif isinstance(key, GrentonCluStateAttributeKey): # pyright: ignore[reportUnnecessaryIsInstance]
                mapped_keys.append(f'{{{key.object_name},{key.name}}}')
        
        payload = f'SYSTEM:clientRegister(0,0,1,{{{",".join(mapped_keys)}}})'
        super().__init__(payload, msg_id)


class GrentonCluApiClientRegisterResponse(GrentonCluApiResponse):
    """Response from client registration with initial values."""
    
    values: list[GrentonValue]
    
    def __init__(self, wire_message: str):
        """Initialize from wire format message and parse values."""
        super().__init__(wire_message)
        self.values = _parse_client_report_payload(self.payload)


class GrentonCluApiClientReportNotification(GrentonCluApiNotification):
    """Notification with subscription report and updated values."""
    
    values: list[GrentonValue]
    
    def __init__(self, wire_message: str):
        """Initialize from wire format message and parse values."""
        super().__init__(wire_message)
        self.values = _parse_client_report_payload(self.payload)
