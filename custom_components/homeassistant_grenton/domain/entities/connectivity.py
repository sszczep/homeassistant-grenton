"""Diagnostic connectivity sensors: one per CLU (UDP) and one for the Gate HTTP (#6)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity


class GrentonEntityConnectivity(BaseGrentonEntity, BinarySensorEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: Any, id: str, label: str, target: str | None,
                 device_info: DeviceInfo | None = None) -> None:
        """target: CLU id for the UDP coordinator, None for the Gate."""
        BinarySensorEntity.__init__(self)
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        self._target = target

    @property
    def clu_ids(self) -> set[str]:
        return set()

    @property
    def available(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        return True  # the sensor itself reports the outage

    @property
    def is_on(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        if self._target is None:
            return bool(self.coordinator.last_update_success)
        return bool(self.coordinator.is_clu_available(self._target))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        if self._target is None:
            return {"url": self.coordinator.client.url}
        last_seen = self.coordinator.last_seen.get(self._target)
        return {"last_seen": last_seen.isoformat() if last_seen else None}
