from __future__ import annotations

from ipaddress import IPv4Address

from ....state import (
    GrentonCluStateAttributeKey,
    GrentonCluStateVariableKey,
    GrentonValue,
)
from ...clu import GrentonClu
from .base import GrentonCluApiNotification, GrentonCluApiRequest, GrentonCluApiResponse
from .state_values import format_state_keys, parse_state_values


def _parse_client_report(
    payload: str,
    keys: list[GrentonCluStateVariableKey | GrentonCluStateAttributeKey] | None = None,
    clu: GrentonClu | None = None,
) -> tuple[int, list[GrentonValue]]:
    """Parse a clientReport payload into (subscription_id, values).

    Wire payload format: clientReport:{SUBSCRIPTION_ID}:{val1,val2,...}
    Reject malformed headers before their values can affect state or health.
    Response attributes retain the legacy session_id name. This numeric field
    identifies the third clientRegister argument, independently of the report
    destination port (the request's legacy session_id argument).
    """
    if not payload.startswith("clientReport:"):
        raise ValueError("Expected a clientReport payload")

    parts = payload.split(":", 2)
    if len(parts) != 3:
        raise ValueError("Incomplete clientReport header")

    try:
        session_id = int(parts[1])
    except ValueError as error:
        raise ValueError("Invalid clientReport session") from error
    if session_id < 0:
        raise ValueError("Invalid clientReport session")

    return session_id, parse_state_values(parts[2], keys, clu)


class GrentonCluApiClientRegisterRequest(GrentonCluApiRequest):
    """Request to register component states for subscription."""

    keys: list[GrentonCluStateVariableKey | GrentonCluStateAttributeKey]
    session_id: int

    def __init__(
        self,
        keys: list[GrentonCluStateVariableKey | GrentonCluStateAttributeKey],
        session_id: int,
        msg_id: str | None = None,
        *,
        subscription_id: int = 1,
        report_ip: str | None = None,
        report_port: int | None = None,
    ):
        """Initialize with keys, legacy report-port argument, and subscription ID."""
        self.keys = keys
        self.session_id = session_id

        if not keys:
            raise ValueError("Cannot create registration request with no keys")
        if type(subscription_id) is not int or subscription_id < 0:
            raise ValueError("Subscription ID must be a non-negative integer")
        self.subscription_id = subscription_id

        port = session_id if report_port is None else report_port
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("Report port must be an integer from 0 to 65535")
        if report_ip is None:
            address = "0"
        else:
            if not isinstance(report_ip, str):
                raise ValueError("Report address must be an IPv4 address")
            try:
                address = f'"{IPv4Address(report_ip)}"'
            except ValueError:
                raise ValueError("Report address must be an IPv4 address") from None
        self.report_ip = report_ip
        self.report_port = port

        payload = (
            f"SYSTEM:clientRegister({address},{port},{subscription_id},"
            f"{format_state_keys(keys)})"
        )
        super().__init__(payload, msg_id)


class GrentonCluApiClientRegisterResponse(GrentonCluApiResponse):
    """Response from client registration with initial values."""

    session_id: int
    values: list[GrentonValue]

    def __init__(
        self,
        wire_message: str,
        keys: list[GrentonCluStateVariableKey | GrentonCluStateAttributeKey]
        | None = None,
        clu: GrentonClu | None = None,
    ):
        """Initialize from wire format message and parse values."""
        try:
            super().__init__(wire_message)
        except ValueError:
            raise ValueError("Invalid clientRegister response envelope") from None
        self.session_id, self.values = _parse_client_report(self.payload, keys, clu)


class GrentonCluApiClientReportNotification(GrentonCluApiNotification):
    """Notification with subscription report and updated values."""

    session_id: int
    values: list[GrentonValue]

    def __init__(
        self,
        wire_message: str,
        keys: list[GrentonCluStateVariableKey | GrentonCluStateAttributeKey]
        | None = None,
        clu: GrentonClu | None = None,
    ):
        """Initialize from wire format message and parse values."""
        super().__init__(wire_message)
        self.session_id, self.values = _parse_client_report(self.payload, keys, clu)
