from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity
from ..enums import GrentonUnit
from ..state_object import GrentonStateObject
from ..action import GrentonAction
from ...coordinator import GrentonCoordinator


class GrentonEntityBistableSwitch(BaseGrentonEntity, SwitchEntity): # pyright: ignore[reportIncompatibleVariableOverride]
    """Bistable switch entity."""

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        unit: GrentonUnit,
        state_object: GrentonStateObject,
        action_on: GrentonAction,
        action_off: GrentonAction,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize bistable switch entity."""
        SwitchEntity.__init__(self)
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        self.unit = unit
        self.state_object = state_object
        self.action_on = action_on
        self.action_off = action_off
        
        # Register state with coordinator
        coordinator.register_component_state(state_object)

    @property
    def is_on(self) -> bool | None: # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the state of the switch."""
        value = self.coordinator.get_value_for_component(self.state_object)
        if value is None:
            return None
        return value == "ON" or value == True

    async def async_turn_on(self, **kwargs: Any):
        """Turn the switch on."""
        await self.coordinator.execute_action(self.action_on)

    async def async_turn_off(self, **kwargs: Any):
        """Turn the switch off."""
        await self.coordinator.execute_action(self.action_off)
