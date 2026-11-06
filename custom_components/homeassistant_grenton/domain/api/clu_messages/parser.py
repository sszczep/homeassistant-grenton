from __future__ import annotations

from .base import GrentonCluApiResponse


class GrentonCluApiMessageParser:
    """Parser for routing messages to appropriate message classes."""

    @staticmethod
    def parse_response(wire_message: str) -> GrentonCluApiResponse | None:
        """Use the same envelope validation for routing and typed responses."""
        try:
            return GrentonCluApiResponse(wire_message)
        except ValueError:
            return None

    @staticmethod
    def is_valid_response(wire_message: str) -> bool:
        return GrentonCluApiMessageParser.parse_response(wire_message) is not None

    @staticmethod
    def is_client_report(wire_message: str) -> bool:
        """Check if wire message is a client report notification.

        Client reports are notifications with msg_id == "00000000" and payload starting with "clientReport:".
        """
        response = GrentonCluApiMessageParser.parse_response(wire_message)
        return response is not None and response.is_client_report
