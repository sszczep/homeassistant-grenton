from dataclasses import dataclass
from typing import Any, Dict

import voluptuous as vol

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.components.sensor.const import DEVICE_CLASS_UNITS
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.const import (CONF_FRIENDLY_NAME, CONF_ICON, CONF_UNIT_OF_MEASUREMENT)
from homeassistant.helpers import selector

from .base import BaseGrentonEntity
from .configurable import ConfigurableEntity, BaseGrentonEntityConfigurationSchema, StepResult, StepDefinition
from ..state_object import GrentonStateObject
from ...coordinator import GrentonCoordinator

@dataclass
class GrentonEntityValueConfigurationSchema(BaseGrentonEntityConfigurationSchema):
    """Configuration schema for value entities (class, unit)."""
    
    @property
    def steps(self) -> list[StepDefinition]:
        return [
            StepDefinition("configure_sensor_class", self._build_step_class_schema),
            StepDefinition("configure_sensor_unit", self._build_step_unit_schema),
        ]
    
    def _build_step_class_schema(self, current: Dict[str, Any], accumulated: Dict[str, Any]) -> StepResult:
        # Build device class options - values only, translations via translation_key
        device_class_options = [dc.value for dc in SensorDeviceClass]
        
        return StepResult(
            schema=vol.Schema(
                {
                    vol.Required(
                        "device_class",
                        default=current.get("device_class")
                    ): selector.SelectSelector(  # type: ignore[misc]
                        selector.SelectSelectorConfig(
                            options=device_class_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            translation_key="device_classes",
                            sort=True,
                        )
                    ),
                }
            )
        )
    
    def _build_step_unit_schema(self, current: Dict[str, Any], accumulated: Dict[str, Any]) -> StepResult:
        # Get device class from accumulated data (step 1)
        device_class_value = accumulated.get("device_class")
        
        # Get compatible units for the selected device class
        unit_options: list[str] = []
        if device_class_value:
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
        
        # If no units available, finish configuration without showing this step
        if not unit_options:
            return StepResult(
                schema=vol.Schema({}),
                complete=True,
            )
        
        return StepResult(
            schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UNIT_OF_MEASUREMENT, 
                        default=current.get(CONF_UNIT_OF_MEASUREMENT)
                    ): selector.SelectSelector(  # type: ignore[misc]
                        selector.SelectSelectorConfig(
                            options=unit_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            )
        )

class GrentonEntityValue( # pyright: ignore[reportIncompatibleVariableOverride]
    BaseGrentonEntity,
    ConfigurableEntity[GrentonEntityValueConfigurationSchema],
    SensorEntity): 
    """Value sensor entity."""

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        state_object: GrentonStateObject,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize value sensor entity."""
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        ConfigurableEntity.__init__(self)
        SensorEntity.__init__(self)

        self.state_object = state_object
        
        # Register state with coordinator
        coordinator.register_component_state(state_object)

    @property
    def native_value(self): # pyright: ignore[reportIncompatibleVariableOverride]
        return self.coordinator.get_value_for_component(self.state_object)

    @property
    def name(self) -> str: # pyright: ignore[reportIncompatibleVariableOverride]
        friendly_name = self._config.get(CONF_FRIENDLY_NAME)
        return friendly_name or self.label
    
    @property
    def icon(self): # pyright: ignore[reportIncompatibleVariableOverride]
        return self._config.get(CONF_ICON)

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
    def native_unit_of_measurement(self): # pyright: ignore[reportIncompatibleVariableOverride]
        return self._config.get(CONF_UNIT_OF_MEASUREMENT)
