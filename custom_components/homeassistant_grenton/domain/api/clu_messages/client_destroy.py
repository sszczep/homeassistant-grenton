"""Remove one report subscription without closing its UDP listener."""

import re
from ipaddress import IPv4Address

from .base import GrentonCluApiRequest, GrentonCluApiResponse


def _validate_subscription_id(subscription_id: int) -> None:
    if type(subscription_id) is not int or subscription_id < 0:
        raise ValueError("Subscription ID must be a non-negative integer")


class GrentonCluApiClientDestroyRequest(GrentonCluApiRequest):
    """Destroy the subscription identified by report address, port and ID."""

    def __init__(
        self,
        subscription_id: int,
        msg_id: str | None = None,
        *,
        report_ip: str | None = None,
        report_port: int = 0,
    ):
        _validate_subscription_id(subscription_id)
        if type(report_port) is not int or not 0 <= report_port <= 65535:
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
        self.subscription_id = subscription_id
        self.report_ip = report_ip
        self.report_port = report_port
        super().__init__(
            f"SYSTEM:clientDestroy({address},{report_port},{subscription_id})",
            msg_id,
        )


class GrentonCluApiClientDestroyResponse(GrentonCluApiResponse):
    """Verify the numeric subscription ID returned by clientDestroy."""

    def __init__(self, wire_message: str, subscription_id: int):
        _validate_subscription_id(subscription_id)
        try:
            super().__init__(wire_message)
        except ValueError:
            raise ValueError("Invalid clientDestroy response envelope") from None
        if not re.fullmatch(r"[0-9]+", self.payload):
            raise ValueError("Invalid clientDestroy acknowledgement")
        try:
            acknowledged_id = int(self.payload)
        except ValueError:
            raise ValueError("Invalid clientDestroy acknowledgement") from None
        if acknowledged_id != subscription_id:
            raise ValueError("Unexpected clientDestroy subscription ID")
        self.subscription_id = acknowledged_id
