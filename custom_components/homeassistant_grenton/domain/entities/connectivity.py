"""Diagnostic connectivity sensor for the Gate HTTP (REST) transport (#6)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity


class GrentonEntityConnectivity(BaseGrentonEntity, BinarySensorEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: Any, id: str, label: str, device_info: DeviceInfo | None = None) -> None:
        BinarySensorEntity.__init__(self)
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)

    @property
    def available(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        return True  # the sensor itself reports the outage

    @property
    def is_on(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        return bool(self.coordinator.last_update_success)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        return {"url": self.coordinator.client.url}
