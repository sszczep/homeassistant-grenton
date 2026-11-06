from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.sensor.const import (
    DEVICE_CLASS_STATE_CLASSES,
    DEVICE_CLASS_UNITS,
)
from homeassistant.const import CONF_UNIT_OF_MEASUREMENT
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from ...coordinator import GrentonCoordinator
from ..enums import GrentonValueType
from ..state_object import GrentonStateObject
from .base import BaseGrentonEntity
from .configurable import (
    BaseGrentonEntityConfigurationSchema,
    ConfigurableEntity,
    StepDefinition,
    StepResult,
)

TEMPORAL_DEVICE_CLASSES = frozenset(
    device_class
    for device_class in SensorDeviceClass
    if device_class.value in ("date", "timestamp", "uptime")
)


def normalize_sensor_config(config: dict[str, Any]) -> dict[str, Any]:
    """Keep generic units while removing units from classes that forbid them."""
    result = dict(config)
    if result.get("device_class") in (None, "", "none"):
        result.pop("device_class", None)
    unit = result.get(CONF_UNIT_OF_MEASUREMENT)
    if isinstance(unit, str):
        unit = unit.strip()
    if (
        not unit
        or unit == "none"
        or result.get("device_class") == SensorDeviceClass.ENUM
        or result.get("device_class") in TEMPORAL_DEVICE_CLASSES
    ):
        result.pop(CONF_UNIT_OF_MEASUREMENT, None)
    else:
        result[CONF_UNIT_OF_MEASUREMENT] = unit
    return result


@dataclass
class GrentonEntityValueConfigurationSchema(BaseGrentonEntityConfigurationSchema):
    """Configuration schema for value entities (class, unit)."""

    @property
    def steps(self) -> list[StepDefinition]:
        return [
            StepDefinition("configure_sensor_class", self._build_step_class_schema),
            StepDefinition("configure_sensor_unit", self._build_step_unit_schema),
        ]

    def _build_step_class_schema(
        self, current: dict[str, Any], accumulated: dict[str, Any]
    ) -> StepResult:
        # Build device class options - values only, translations via translation_key
        device_class_options = [dc.value for dc in SensorDeviceClass]

        return StepResult(
            schema=vol.Schema(
                {
                    vol.Required(
                        "device_class", default=current.get("device_class")
                    ): selector.SelectSelector(  # type: ignore[misc]
                        selector.SelectSelectorConfig(
                            options=device_class_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            translation_key="sensor_device_classes",
                            sort=True,
                        )
                    ),
                }
            )
        )

    def _build_step_unit_schema(
        self, current: dict[str, Any], accumulated: dict[str, Any]
    ) -> StepResult:
        # Get device class from accumulated data (step 1)
        device_class_value = accumulated.get("device_class")

        generic = device_class_value in (None, "", "none")
        # Classified sensors accept only the units supported by Home Assistant.
        unit_options: list[str] = []
        if generic:
            unit_options = ["none", "%"]
            unit = current.get(CONF_UNIT_OF_MEASUREMENT)
            if isinstance(unit, str):
                unit = unit.strip()
                if unit and unit not in unit_options:
                    unit_options.append(unit)
        else:
            try:
                device_class = SensorDeviceClass(device_class_value)
                units = DEVICE_CLASS_UNITS.get(device_class, set())
                # Convert units to strings, handling None and enum values
                for unit in units:
                    if unit is None:
                        unit_options.append("none")
                    elif hasattr(unit, "value") and not isinstance(unit, str):
                        # It's a StrEnum, get the value
                        unit_options.append(str(unit.value))
                    else:
                        # It's already a string
                        unit_options.append(str(unit))
            except (ValueError, KeyError):
                pass
            unit_options.sort()

        # If no units available, finish configuration without showing this step
        if not unit_options:
            return StepResult(
                schema=vol.Schema({}),
                complete=True,
            )

        default = current.get(CONF_UNIT_OF_MEASUREMENT)
        if isinstance(default, str):
            default = default.strip()
        if default not in unit_options:
            default = unit_options[0]
        return StepResult(
            schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UNIT_OF_MEASUREMENT, default=default
                    ): selector.SelectSelector(  # type: ignore[misc]
                        selector.SelectSelectorConfig(
                            options=unit_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            custom_value=generic,
                            translation_key="sensor_units",
                        )
                    ),
                }
            )
        )


class GrentonEntityValue(  # pyright: ignore[reportIncompatibleVariableOverride]
    BaseGrentonEntity,
    ConfigurableEntity[GrentonEntityValueConfigurationSchema],
    SensorEntity,
):
    """Value sensor entity."""

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        state_object: GrentonStateObject,
        value_type: GrentonValueType | None = None,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize value sensor entity."""
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        ConfigurableEntity.__init__(self)
        SensorEntity.__init__(self)

        self.state_object = state_object
        self.value_type = value_type

        # Register state with coordinator
        self._register_state(state_object)

    @property
    def native_value(self):  # pyright: ignore[reportIncompatibleVariableOverride]
        value = self.coordinator.get_value_for_component(self.state_object)
        if value is None:
            return None
        if self.device_class in TEMPORAL_DEVICE_CLASSES:
            if isinstance(value, bool):
                return None
            try:
                seconds = float(value)
                if not isfinite(seconds):
                    return None
                timestamp = datetime.fromtimestamp(seconds, UTC)
            except (ValueError, TypeError, OverflowError, OSError):
                return None
            if self.device_class == SensorDeviceClass.DATE:
                hass = self.hass or getattr(self.coordinator, "hass", None)
                if hass is not None:
                    time_zone = dt_util.get_time_zone(hass.config.time_zone)
                    if time_zone is not None:
                        timestamp = timestamp.astimezone(time_zone)
                return timestamp.date()
            return timestamp
        if self.value_type == GrentonValueType.FLOAT:
            try:
                return float(value)
            except (ValueError, TypeError):
                return value
        if self.value_type == GrentonValueType.INTEGER:
            try:
                return int(float(value))
            except (ValueError, TypeError):
                return value
        return value

    @property
    def state_class(self) -> SensorStateClass | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        if (
            self.device_class is not None
            and SensorStateClass.MEASUREMENT
            not in DEVICE_CLASS_STATE_CLASSES.get(self.device_class, set())
        ):
            return None
        if self.value_type in (GrentonValueType.FLOAT, GrentonValueType.INTEGER):
            return SensorStateClass.MEASUREMENT
        return None

    @property
    def device_class(self) -> SensorDeviceClass | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        device_class = self._config.get("device_class")
        if device_class:
            try:
                return SensorDeviceClass(device_class)
            except ValueError:
                return None
        return None

    @property
    def native_unit_of_measurement(self):  # pyright: ignore[reportIncompatibleVariableOverride]
        if (
            self.device_class == SensorDeviceClass.ENUM
            or self.device_class in TEMPORAL_DEVICE_CLASSES
        ):
            return None
        return self._config.get(CONF_UNIT_OF_MEASUREMENT)
