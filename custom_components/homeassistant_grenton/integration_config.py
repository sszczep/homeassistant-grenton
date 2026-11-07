"""Configuration types for Grenton integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypedDict

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .coordinator import GrentonCoordinator
    from .domain.devices.base import BaseGrentonDevice
    from homeassistant.helpers.entity import Entity


class GrentonConfigEntryData(TypedDict):
    """Type definition for config entry data."""

    ip_address: str
    port: int
    pin: str
    interface: dict[str, Any]


@dataclass
class RuntimeData:
    """Runtime data stored in config entry."""

    coordinator: GrentonCoordinator
    devices: list[BaseGrentonDevice]
    clu_entities: list[Entity] = field(default_factory=list)
    gate_coordinator: Any = None
    # Snapshot of options that require a reload when changed
    structural_options: Any = None
    restore_manager: Any = None


type GrentonConfigEntry = ConfigEntry[RuntimeData]
