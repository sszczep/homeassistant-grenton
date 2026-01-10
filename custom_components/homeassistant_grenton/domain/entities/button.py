from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity
from ..action import GrentonAction
from ...coordinator import GrentonCoordinator


class GrentonEntityButton(BaseGrentonEntity, ButtonEntity): # pyright: ignore[reportIncompatibleVariableOverride]
    """Button entity."""

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        action_click: GrentonAction,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize button entity."""
        ButtonEntity.__init__(self)
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        self.action_click = action_click

    async def async_press(self, **kwargs: Any):
        """Press the button."""
        await self.coordinator.execute_action(self.action_click)
