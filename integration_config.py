"""Configuration types for Grenton integration."""

from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypedDict

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .coordinator import GrentonCoordinator
    from .domain.devices.base import BaseGrentonDevice


class GrentonConfigEntryData(TypedDict):
    """Type definition for config entry data."""
    ip_address: str
    port: int
    pin: str
    interface: dict[str, Any]


@dataclass
class RuntimeData:
    """Runtime data stored in config entry."""
    coordinator: "GrentonCoordinator"
    devices: list["BaseGrentonDevice"]


type GrentonConfigEntry = ConfigEntry[RuntimeData]
