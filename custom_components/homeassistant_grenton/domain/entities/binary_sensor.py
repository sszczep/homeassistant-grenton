from dataclasses import dataclass
from typing import Any, Dict

import voluptuous as vol

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import selector

from .base import BaseGrentonEntity
from .configurable import ConfigurableEntity, BaseGrentonEntityConfigurationSchema, StepResult, StepDefinition
from ..state_object import GrentonStateObject
from ...coordinator import GrentonCoordinator

@dataclass
class GrentonEntityBinarySensorConfigurationSchema(BaseGrentonEntityConfigurationSchema):
    """Configuration schema for value entities (class, unit)."""
    
    @property
    def steps(self) -> list[StepDefinition]:
        return [
            StepDefinition("configure_binary_sensor_class", self._build_step_class_schema),
        ]
    
    def _build_step_class_schema(self, current: Dict[str, Any], accumulated: Dict[str, Any]) -> StepResult:
        # Build device class options - values only, translations via translation_key
        device_class_options = [dc.value for dc in BinarySensorDeviceClass]
        
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
                            translation_key="binary_sensor_device_classes",
                            sort=True,
                        )
                    ),
                }
            )
        )

class GrentonEntityBinarySensor( # pyright: ignore[reportIncompatibleVariableOverride]
    BaseGrentonEntity,
    ConfigurableEntity[GrentonEntityBinarySensorConfigurationSchema],
    BinarySensorEntity): 
    """Binary sensor entity."""
    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        reversed: bool,
        state_object: GrentonStateObject,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize binary sensor entity."""
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        ConfigurableEntity.__init__(self)
        BinarySensorEntity.__init__(self)

        self.reversed = reversed
        self.state_object = state_object
        
        # Register state with coordinator
        coordinator.register_component_state(state_object)

    @property
    def is_on(self) -> bool | None: # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the state of the switch."""
        value = self.coordinator.get_value_for_component(self.state_object)
        if value is None:
            return None
        return not bool(value) if self.reversed else bool(value)

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        device_class = self._config.get("device_class")
        if device_class:
            try:
                return BinarySensorDeviceClass(device_class)
            except ValueError:
                return None
        return None
