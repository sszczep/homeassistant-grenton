from typing import Any

from homeassistant.components.light import LightEntity
from homeassistant.components.light.const import ColorMode
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity
from ..action import GrentonAction
from ..state_object import GrentonStateObject


class GrentonEntityOnOffLight(BaseGrentonEntity, LightEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    """On/off light (e.g. a DOUT relay driving a lamp)."""

    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(
        self,
        coordinator: Any,
        id: str,
        label: str,
        state_object: GrentonStateObject,
        action_on: GrentonAction,
        action_off: GrentonAction,
        device_info: DeviceInfo | None = None,
    ) -> None:
        LightEntity.__init__(self)
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        self.state_object = state_object
        self.action_on = action_on
        self.action_off = action_off
        coordinator.register_component_state(state_object)

    @property
    def is_on(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        value = self.coordinator.get_value_for_component(self.state_object)
        if value is None or value == "":
            return None
        try:
            return float(value) > 0  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return value in (True, "ON")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.execute_action(self.action_on)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.execute_action(self.action_off)
