from dataclasses import dataclass
from typing import Any, Dict

import voluptuous as vol

from homeassistant.components.number import NumberEntity, NumberDeviceClass
from homeassistant.components.number.const import DEVICE_CLASS_UNITS
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.const import CONF_UNIT_OF_MEASUREMENT
from homeassistant.helpers import selector

from .base import BaseGrentonEntity
from .configurable import ConfigurableEntity, BaseGrentonEntityConfigurationSchema, StepResult, StepDefinition
from ..state_object import GrentonStateObject
from ...coordinator import GrentonCoordinator
from ..action import GrentonAction

@dataclass
class GrentonEntitySliderConfigurationSchema(BaseGrentonEntityConfigurationSchema):
    """Configuration schema for slider entities (class, unit, display mode)."""
    
    @property
    def steps(self) -> list[StepDefinition]:
        return [
            StepDefinition("configure_slider_mode", self._build_step_mode_schema),
            StepDefinition("configure_slider_class", self._build_step_class_schema),
            StepDefinition("configure_slider_unit", self._build_step_unit_schema),
        ]
    
    def _build_step_mode_schema(self, current: Dict[str, Any], accumulated: Dict[str, Any]) -> StepResult:
        return StepResult(
            schema=vol.Schema(
                {
                    vol.Required(
                        "mode",
                        default=current.get("mode") or "slider"
                    ): selector.SelectSelector(  # type: ignore[misc]
                        selector.SelectSelectorConfig(
                            options=["auto", "slider", "box"],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            translation_key="slider_modes",
                        )
                    ),
                }
            )
        )
    
    def _build_step_class_schema(self, current: Dict[str, Any], accumulated: Dict[str, Any]) -> StepResult:
        # Build device class options - values only, translations via translation_key
        device_class_options = [dc.value for dc in NumberDeviceClass]
        
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
                            translation_key="slider_device_classes",
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
                device_class = NumberDeviceClass(device_class_value)
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

class GrentonEntitySlider( # pyright: ignore[reportIncompatibleVariableOverride]
    BaseGrentonEntity,
    ConfigurableEntity[GrentonEntitySliderConfigurationSchema],
    NumberEntity): 
    """Slider entity."""

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        min: float,
        max: float,
        precision: int,
        state_object: GrentonStateObject,
        action_set_value: GrentonAction,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize value sensor entity."""
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        ConfigurableEntity.__init__(self)
        NumberEntity.__init__(self)

        self.min = min
        self.max = max
        self.precision = precision
        self.state_object = state_object
        self.action_set_value = action_set_value
        
        # Register state with coordinator
        coordinator.register_component_state(state_object)

    @property
    def native_min_value(self): # pyright: ignore[reportIncompatibleVariableOverride]
        return self.min
    
    @property
    def native_max_value(self): # pyright: ignore[reportIncompatibleVariableOverride]
        return self.max
    
    @property
    def native_step(self): # pyright: ignore[reportIncompatibleVariableOverride]
        return 10 ** (-self.precision)

    @property
    def native_value(self): # pyright: ignore[reportIncompatibleVariableOverride]
        return self.coordinator.get_value_for_component(self.state_object)
    
    async def async_set_native_value(self, value: float) -> None:  # pyright: ignore[reportIncompatibleVariableOverride]
        self.action_set_value.value = str(round(value, self.precision))
        await self.coordinator.execute_action(self.action_set_value)
    
    @property
    def mode(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        mode = self._config.get("mode")
        if mode in ["auto", "slider", "box"]:
            return mode
        return "slider"

    @property
    def device_class(self) -> NumberDeviceClass | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        device_class = self._config.get("device_class")
        if device_class:
            try:
                return NumberDeviceClass(device_class)
            except ValueError:
                return None
        return None

    @property
    def native_unit_of_measurement(self): # pyright: ignore[reportIncompatibleVariableOverride]
        return self._config.get(CONF_UNIT_OF_MEASUREMENT)
