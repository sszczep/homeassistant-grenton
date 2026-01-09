from typing import Any

from homeassistant.components.light import LightEntity, ATTR_BRIGHTNESS
from homeassistant.components.light.const import ColorMode

from .base import BaseGrentonEntity
from ..action import GrentonAction
from ..state_object import GrentonStateObject
from ...coordinator import GrentonCoordinator
from homeassistant.helpers.device_registry import DeviceInfo

from ..utils.ranges import map_range

class GrentonEntityDimmer(BaseGrentonEntity, LightEntity): # pyright: ignore[reportIncompatibleVariableOverride]
    """Dimmer light entity."""

    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        min: float,
        max: float,
        precision: int,
        state_object: GrentonStateObject,
        action_on: GrentonAction,
        action_off: GrentonAction,
        action_set_value: GrentonAction,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize dimmer light entity."""
        LightEntity.__init__(self)
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        self.min = min
        self.max = max
        self.precision = precision
        self.state_object = state_object
        self.action_on = action_on
        self.action_off = action_off
        self.action_set_value = action_set_value
        
        # Register state with coordinator
        coordinator.register_component_state(state_object)

    @property
    def is_on(self) -> bool | None: # pyright: ignore[reportIncompatibleVariableOverride]
        """Return whether the light is on."""
        value = self.coordinator.get_value_for_component(self.state_object)
        if value is None:
            return None
        return float(value) > 0

    @property
    def brightness(self) -> int | None: # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the brightness of the light (0-255)."""
        value = self.coordinator.get_value_for_component(self.state_object)
        if value is None:
            return None
        # Convert from device range to Home Assistant range (0-255)
        value = float(value)
        return int(map_range((self.min, self.max), (0, 255), value))

    async def async_turn_on(self, **kwargs: Any):
        """Turn the light on."""
        if ATTR_BRIGHTNESS in kwargs:
            # Convert from HA range (0-255) to device range
            brightness: int = kwargs[ATTR_BRIGHTNESS]
            device_value = map_range((0, 255), (self.min, self.max), brightness)
            self.action_set_value.value = str(round(device_value, self.precision))
            await self.coordinator.execute_action(self.action_set_value)
        else:
            await self.coordinator.execute_action(self.action_on)

    async def async_turn_off(self, **kwargs: Any):
        """Turn the light off."""
        await self.coordinator.execute_action(self.action_off)
