"""LED RGB / RGBW controller addressed by object (manual objects).

Features/methods (Z-Wave objects use the alternative colour index):
    get(0)  brightness 0..1           execute(0, x)  set brightness (0 = off)
    get(6)  colour "#rrggbb"          execute(6, "#rrggbb")   (Z-Wave: 3 / 3)
    get(15) white channel 0..255      execute(12, w)          (RGBW only)
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ATTR_WHITE,
    ColorMode,
    LightEntity,
)
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity
from ..action import GrentonActionMethod, GrentonActionMethodNumeric
from ..enums import GrentonActionEventType
from ..state_object import GrentonAttributeValueObject


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hex_to_rgb(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


class GrentonEntityLedHex(BaseGrentonEntity, LightEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    def __init__(
        self,
        coordinator: Any,
        id: str,
        label: str,
        clu_id: str,
        object_name: str,
        white: bool,
        zwave: bool = False,
        device_info: DeviceInfo | None = None,
    ) -> None:
        LightEntity.__init__(self)
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        colour_index = 3 if zwave else 6
        self._has_white = white

        def state(index: int) -> GrentonAttributeValueObject:
            return GrentonAttributeValueObject(clu_id=clu_id, object_name=object_name, index=str(index))

        self._value_state = state(0)
        self._colour_state = state(colour_index)
        self._white_state = state(15) if white else None
        for obj in (self._value_state, self._colour_state, self._white_state):
            if obj is not None:
                coordinator.register_component_state(obj)

        click = GrentonActionEventType.CLICK
        self._set_value = GrentonActionMethodNumeric(clu_id, object_name, click, "0", index="0")
        # Colour is a Lua string -> quoted action
        self._set_colour = GrentonActionMethod(clu_id, object_name, click, "#ffffff", index=str(colour_index))
        self._set_white = GrentonActionMethodNumeric(clu_id, object_name, click, "0", index="12")
        self._last_value = 1.0
        self._last_white = 255.0

        modes = {ColorMode.RGB, ColorMode.WHITE} if white else {ColorMode.RGB}
        self._attr_supported_color_modes = modes

    # --- state --------------------------------------------------------------
    def _get(self, obj: GrentonAttributeValueObject | None) -> Any:
        return self.coordinator.get_value_for_component(obj) if obj is not None else None

    @property
    def _value(self) -> float | None:
        return _float(self._get(self._value_state))

    @property
    def _white(self) -> float | None:
        return _float(self._get(self._white_state)) if self._has_white else None

    @property
    def color_mode(self) -> ColorMode:  # pyright: ignore[reportIncompatibleVariableOverride]
        if self._has_white and (self._white or 0) > 0 and not (self._value or 0) > 0:
            return ColorMode.WHITE
        return ColorMode.RGB

    @property
    def is_on(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        value, white = self._value, self._white
        if value is None and white is None:
            return None
        return (value or 0) > 0 or (white or 0) > 0

    @property
    def brightness(self) -> int | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        if self.color_mode == ColorMode.WHITE:
            white = self._white
            return None if white is None else int(max(0, min(255, white)))
        value = self._value
        return None if value is None else int(round(max(0.0, min(1.0, value)) * 255))

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        return _hex_to_rgb(self._get(self._colour_state))

    # --- commands -------------------------------------------------------------
    async def _send_value(self, value: float) -> None:
        await self.coordinator.execute_action(replace(self._set_value, value=str(round(value, 3))))

    async def _send_white(self, white: float) -> None:
        await self.coordinator.execute_action(replace(self._set_white, value=str(int(white))))

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._has_white and ATTR_WHITE in kwargs:
            white = float(kwargs[ATTR_WHITE]) or self._last_white
            self._last_white = white
            await self._send_value(0)
            await self._send_white(white)
            return

        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if brightness is not None and self.color_mode == ColorMode.WHITE and ATTR_RGB_COLOR not in kwargs:
            self._last_white = float(brightness)
            await self._send_white(brightness)
            return

        if ATTR_RGB_COLOR in kwargs:
            red, green, blue = kwargs[ATTR_RGB_COLOR]
            colour = f"#{int(red):02x}{int(green):02x}{int(blue):02x}"
            await self.coordinator.execute_action(replace(self._set_colour, value=colour))
            if self._has_white:
                await self._send_white(0)

        if brightness is not None:
            value = max(0.0, min(1.0, float(brightness) / 255))
        elif (self._value or 0) > 0:
            return
        else:
            value = self._last_value
        if value > 0:
            self._last_value = value
        await self._send_value(value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if (self._value or 0) > 0:
            self._last_value = self._value or self._last_value
        if self._has_white and (self._white or 0) > 0:
            self._last_white = self._white or self._last_white
        await self._send_value(0)
        if self._has_white:
            await self._send_white(0)
