from __future__ import annotations


class GrentonCluApiMessageParser:
    """Parser for routing messages to appropriate message classes."""
    
    @staticmethod
    def is_valid_response(wire_message: str) -> bool:
        """Check if message is a valid response format."""
        if not wire_message.startswith("resp:"):
            return False
        
        parts = wire_message.split(":", 3)
        return len(parts) == 4
    
    @staticmethod
    def is_client_report(wire_message: str) -> bool:
        """Check if wire message is a client report notification.
        
        Client reports are notifications with msg_id == "00000000" and payload starting with "clientReport:".
        """
        if not wire_message.startswith("resp:"):
            return False
        
        parts = wire_message.split(":", 3)
        if len(parts) == 4:
            msg_id = parts[2].lower()
            payload = parts[3]
            return msg_id == "00000000" and payload.startswith("clientReport:")
        
        return False
