from typing import Any

from homeassistant.components.light import LightEntity, ATTR_BRIGHTNESS, ATTR_HS_COLOR, ATTR_WHITE
from homeassistant.components.light.const import ColorMode

from .base import BaseGrentonEntity
from ..action import GrentonAction
from ..state_object import GrentonStateObject
from ...coordinator import GrentonCoordinator
from homeassistant.helpers.device_registry import DeviceInfo

from ..utils.ranges import map_range

class GrentonEntityLed(BaseGrentonEntity, LightEntity): # pyright: ignore[reportIncompatibleVariableOverride]
    """LED light entity with RGB (hue/saturation) and a dedicated white channel."""

    _attr_supported_color_modes = {ColorMode.HS, ColorMode.WHITE}

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        state_object: GrentonStateObject,
        action_on: GrentonAction,
        action_off: GrentonAction,
        hue_action: GrentonAction,
        hue_state_object: GrentonStateObject,
        hue_range: tuple[float, float],
        saturation_action: GrentonAction,
        saturation_state_object: GrentonStateObject,
        saturation_range: tuple[float, float],
        brightness_action: GrentonAction,
        brightness_state_object: GrentonStateObject,
        brightness_range: tuple[float, float],
        white_action: GrentonAction,
        white_state_object: GrentonStateObject,
        white_range: tuple[float, float],
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize dimmer light entity."""
        LightEntity.__init__(self)
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        self.state_object = state_object
        self.action_on = action_on
        self.action_off = action_off
        self.hue_action = hue_action
        self.hue_state_object = hue_state_object
        self.hue_range = hue_range
        self.saturation_action = saturation_action
        self.saturation_state_object = saturation_state_object
        self.saturation_range = saturation_range
        self.brightness_action = brightness_action
        self.brightness_state_object = brightness_state_object
        self.brightness_range = brightness_range
        self.white_action = white_action
        self.white_state_object = white_state_object
        self.white_range = white_range

        # Register state with coordinator
        coordinator.register_component_state(state_object)
        coordinator.register_component_state(hue_state_object)
        coordinator.register_component_state(saturation_state_object)
        coordinator.register_component_state(brightness_state_object)
        coordinator.register_component_state(white_state_object)

    def _white_value(self) -> float | None:
        """Return the raw white channel value, or None when unknown."""
        value = self.coordinator.get_value_for_component(self.white_state_object)
        if value is None:
            return None
        return float(value)

    @property
    def color_mode(self) -> ColorMode: # pyright: ignore[reportIncompatibleVariableOverride]
        """Report WHITE while the white channel is lit, otherwise HS."""
        white = self._white_value()
        if white is not None and white > 0:
            return ColorMode.WHITE
        return ColorMode.HS

    @property
    def is_on(self) -> bool | None: # pyright: ignore[reportIncompatibleVariableOverride]
        """Return whether the light is on (color channel or white channel)."""
        value = self.coordinator.get_value_for_component(self.state_object)
        white = self._white_value()
        if value is None and white is None:
            return None
        if value is not None and bool(value):
            return True
        if white is not None and white > 0:
            return True
        return False

    @property
    def brightness(self) -> int | None: # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the brightness of the active channel (0-255)."""
        white = self._white_value()
        if white is not None and white > 0:
            return int(map_range(self.white_range, (0, 255), white))
        value = self.coordinator.get_value_for_component(self.brightness_state_object)
        if value is None:
            return None
        # Convert from device range to Home Assistant range (0-255)
        return int(map_range(self.brightness_range, (0, 255), float(value)))

    @property
    def hs_color(self) -> tuple[float, float] | None: # pyright: ignore[reportIncompatibleVariableOverride]
        hue_value = self.coordinator.get_value_for_component(self.hue_state_object)
        saturation_value = self.coordinator.get_value_for_component(self.saturation_state_object)
        if hue_value is None or saturation_value is None:
            return None
        hue = map_range(self.hue_range, (0, 360), float(hue_value))
        saturation = map_range(self.saturation_range, (0, 100), float(saturation_value))
        return (hue, saturation)

    async def _set_white(self, value: float) -> None:
        """Set the white channel to a device-range value."""
        self.white_action.value = str(round(value, 2))
        await self.coordinator.execute_action(self.white_action)

    async def async_turn_on(self, **kwargs: Any):
        """Turn the light on.

        On the LED object the on/off button and the brightness slider are the
        same SetValue method (index 0), so calling action_on after setting a
        brightness would override it back to full. White (index 12) is an
        independent channel; RGB and white are mutually exclusive in HA's color
        model, so selecting one clears the other.
        """
        if ATTR_WHITE in kwargs:
            white: int = kwargs[ATTR_WHITE]
            await self._set_white(map_range((0, 255), self.white_range, white))
            # Zero the RGB value so only the white channel stays lit.
            await self.coordinator.execute_action(self.action_off)
            return

        if ATTR_HS_COLOR in kwargs:
            hs_color: tuple[float, float] = kwargs[ATTR_HS_COLOR]
            hue, saturation = hs_color
            # Convert from HA range to device range
            hue_device_value = map_range((0, 360), self.hue_range, hue)
            saturation_device_value = map_range((0, 100), self.saturation_range, saturation)
            self.hue_action.value = str(round(hue_device_value, 2))
            self.saturation_action.value = str(round(saturation_device_value, 2))
            await self.coordinator.execute_action(self.hue_action)
            await self.coordinator.execute_action(self.saturation_action)
        if ATTR_BRIGHTNESS in kwargs:
            # Convert from HA range (0-255) to device range
            brightness: int = kwargs[ATTR_BRIGHTNESS]
            device_value = map_range((0, 255), self.brightness_range, brightness)
            self.brightness_action.value = str(round(device_value, 2))
            await self.coordinator.execute_action(self.brightness_action)

        if ATTR_HS_COLOR in kwargs or ATTR_BRIGHTNESS in kwargs:
            # Leaving white mode for a color: clear the white channel.
            await self._set_white(self.white_range[0])

        if ATTR_BRIGHTNESS not in kwargs:
            # No explicit brightness (plain toggle or color-only): switch on.
            await self.coordinator.execute_action(self.action_on)

    async def async_turn_off(self, **kwargs: Any):
        """Turn the light off, including the white channel."""
        await self._set_white(self.white_range[0])
        await self.coordinator.execute_action(self.action_off)
