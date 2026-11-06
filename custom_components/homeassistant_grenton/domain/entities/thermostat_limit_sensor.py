"""Reported thermostat bounds, sharing the climate entity's subscriptions."""

from typing import cast

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity
from .thermostat_v2 import GrentonEntityThermostatV2


class GrentonThermostatLimitSensor(BaseGrentonEntity, SensorEntity):
    """Expose the actual CLU limit without inventing a fallback value."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(
        self, thermostat: GrentonEntityThermostatV2, id: str, minimum: bool
    ) -> None:
        super().__init__(
            thermostat.coordinator,
            id,
            thermostat.label,
            cast(DeviceInfo | None, thermostat.device_info),
        )
        self.thermostat = thermostat
        self._binding = "minTemperature" if minimum else "maxTemperature"
        self._attr_translation_key = (
            "thermostat_minimum" if minimum else "thermostat_maximum"
        )

    @property
    def native_value(self) -> float | None:
        return self.thermostat._number(self._binding)
