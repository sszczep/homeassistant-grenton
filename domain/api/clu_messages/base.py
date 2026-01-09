from __future__ import annotations
import secrets


class GrentonCluApiRequest:
    """Base class for CLU API request messages.
    
    Wire format: req::{MESSAGE ID}:{PAYLOAD}
    """
    
    msg_id: str
    payload: str
    raw: str
    
    def __init__(self, payload: str, msg_id: str | None = None):
        """Initialize with payload and optional message ID.
        
        Args:
            payload: The payload string to execute
            msg_id: Unique message ID for tracking (defaults to random hex)
        """
        self.payload = payload
        self.msg_id = (msg_id or secrets.token_hex(4)).lower()
        self.raw = f"req::{self.msg_id}:{self.payload}"


class GrentonCluApiResponse:
    """Base class for CLU API response messages.
    
    Wire format: resp:<CLU IP>:<MSG ID>:<PAYLOAD>
    """
    
    clu_ip: str
    msg_id: str
    payload: str
    raw: str
    
    def __init__(self, wire_message: str):
        """Initialize from wire format message.
        
        Args:
            wire_message: Wire format: resp:{CLU IP}:{MESSAGE ID}:{PAYLOAD}
            
        Raises:
            ValueError: If wire message format is invalid
        """
        if not wire_message.startswith("resp:"):
            raise ValueError(f"Message does not start with 'resp:': {wire_message}")
        
        parts = wire_message.split(":", 3)
        if len(parts) != 4:
            raise ValueError(f"Invalid wire message format: {wire_message}")
        
        _, self.clu_ip, self.msg_id, self.payload = parts
        self.msg_id = self.msg_id.lower()
        self.raw = wire_message


class GrentonCluApiNotification(GrentonCluApiResponse):
    """Base class for CLU notifications.
    
    Notifications are unsolicited messages sent by the CLU with msg_id == "00000000".
    They share the same wire format as responses but are not replies to requests.
    """
    
    def __init__(self, wire_message: str):
        """Initialize from wire format message."""
        super().__init__(wire_message)
