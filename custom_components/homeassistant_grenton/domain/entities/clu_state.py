"""Built-in CLU diagnostics and cloud configuration."""

from math import isfinite
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory, UnitOfElectricPotential, UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from ...coordinator import GrentonCoordinator
from ...state import GrentonValue
from ..action import GrentonActionAttribute
from ..clu import GrentonClu
from ..device_types import attribute_index
from ..enums import GrentonActionEventType
from ..state_object import GrentonAttributeValueObject
from .base import GrentonStateEntity
from .clu import GrentonCluEntity, clu_device_info
from .clu_diagnostics import connection_diagnostics
from .clu_variables import custom_variable_entities


def _boolean(value: GrentonValue) -> bool | None:
    """Treat missing or invalid values as unknown, rather than disconnected."""
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
    return None


class GrentonCluStateEntity(GrentonStateEntity):
    """A built-in attribute belonging to the existing CLU device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        clu: GrentonClu,
        attribute: str,
        key: str,
        *,
        read_mode: str = "realtime",
    ) -> None:
        super().__init__(coordinator)
        self.clu = clu
        if (index := attribute_index(clu.device_type, attribute)) is None:
            raise ValueError(f"CLU {clu.id} does not support {attribute}")
        self.state_object = GrentonAttributeValueObject(clu.id, clu.object_name, index)
        self._attr_unique_id = f"clu_{clu.id}_{key.removeprefix('clu_')}"
        self._attr_translation_key = key
        self._attr_device_info = clu_device_info(clu)
        coordinator.register_component_state(self.state_object, read_mode=read_mode)

    @property
    def _value(self) -> GrentonValue:
        return self.coordinator.get_value_for_component(self.state_object)


class GrentonCluUptime(GrentonCluStateEntity, SensorEntity):
    """Elapsed running time reported by the CLU, in seconds."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: GrentonCoordinator, clu: GrentonClu) -> None:
        # Uptime changes continuously. Subscribing to it makes the CLU send
        # the entire realtime group on every tick, even if other values stay put.
        super().__init__(coordinator, clu, "Uptime", "clu_uptime", read_mode="slow")

    @property
    def native_value(self) -> int | None:
        value = self._value
        if isinstance(value, bool) or value is None:
            return None
        try:
            seconds = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if seconds < 0 or (isinstance(value, float) and seconds != value):
            return None
        return seconds


class GrentonCluCloudConnection(GrentonCluStateEntity, BinarySensorEntity):
    """Report cloud connectivity independently of the connector setting."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: GrentonCoordinator, clu: GrentonClu) -> None:
        super().__init__(
            coordinator, clu, "CloudConnection", "clu_cloud_connection", read_mode="slow"
        )

    @property
    def is_on(self) -> bool | None:
        return _boolean(self._value)


class GrentonCluFirmwareVersion(GrentonCluStateEntity, SensorEntity):
    """Expose firmware version and keep the device metadata up to date."""

    _attr_icon = "mdi:chip"

    def __init__(self, coordinator: GrentonCoordinator, clu: GrentonClu) -> None:
        super().__init__(
            coordinator, clu, "FirmwareVersion", "clu_firmware_version", read_mode="slow"
        )

    @property
    def native_value(self) -> str | None:
        value = self._value
        return (
            str(value)
            if value is not None and value != "" and not isinstance(value, bool)
            else None
        )

    @property
    def device_info(self) -> DeviceInfo:
        info = clu_device_info(self.clu)
        if version := self.native_value:
            info["sw_version"] = version
        return info

    @callback
    def _handle_coordinator_update(self) -> None:
        if (
            (version := self.native_value)
            and (entry := self.registry_entry)
            and entry.device_id
        ):
            registry = dr.async_get(self.hass)
            device = registry.async_get(entry.device_id)
            if isinstance(device, dr.DeviceEntry) and device.sw_version != version:
                registry.async_update_device(device.id, sw_version=version)
        super()._handle_coordinator_update()


class GrentonCluUseCloud(GrentonCluStateEntity, SwitchEntity):
    """Configure the CLU's cloud connector through its boolean attribute."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:cloud-outline"

    def __init__(self, coordinator: GrentonCoordinator, clu: GrentonClu) -> None:
        super().__init__(
            coordinator, clu, "UseCloud", "clu_use_cloud", read_mode="slow"
        )

    @property
    def is_on(self) -> bool | None:
        return _boolean(self._value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_enabled(False)

    async def _set_enabled(self, enabled: bool) -> None:
        literal = "true" if enabled else "false"
        action = GrentonActionAttribute(
            clu_id=self.clu.id,
            object_name=self.state_object.object_name,
            index=self.state_object.index,
            event=GrentonActionEventType.ON if enabled else GrentonActionEventType.OFF,
            value=literal,
            lua_value=literal,
        )
        await self.coordinator.execute_action(action, raise_on_error=True)
        await self.coordinator.async_refresh_clu_state(self.clu.id)


class GrentonCluBusVoltage(GrentonCluStateEntity, SensorEntity):
    """Monitor bus voltage on CLU types that provide this attribute."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: GrentonCoordinator, clu: GrentonClu) -> None:
        super().__init__(
            coordinator, clu, "BusVoltage", "clu_bus_voltage", read_mode="slow"
        )

    @property
    def native_value(self) -> float | None:
        value = self._value
        if value is None or isinstance(value, bool) or value == "":
            return None
        try:
            voltage = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return voltage if isfinite(voltage) else None


def clu_entities(coordinator: GrentonCoordinator, clu: GrentonClu) -> list[Entity]:
    """Discover built-in entities independently of mobile-interface widgets."""
    controller = GrentonCluEntity(coordinator, clu)
    entities: list[Entity] = [controller]
    for attribute, entity_class in (
        ("Uptime", GrentonCluUptime),
        ("CloudConnection", GrentonCluCloudConnection),
        ("UseCloud", GrentonCluUseCloud),
        ("FirmwareVersion", GrentonCluFirmwareVersion),
        ("BusVoltage", GrentonCluBusVoltage),
    ):
        if attribute_index(clu.device_type, attribute) is not None:
            entities.append(entity_class(coordinator, clu))
    entities.extend(connection_diagnostics(coordinator, clu))
    entities.extend(custom_variable_entities(coordinator, clu))
    return entities
