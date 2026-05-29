from dataclasses import replace
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity
from ..action import GrentonActionScript
from ...coordinator import GrentonCoordinator


class GrentonEntitySceneButton(BaseGrentonEntity, ButtonEntity): # pyright: ignore[reportIncompatibleVariableOverride]
    """Button entity that runs a Grenton script and accepts a runtime parameter."""

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        script_action: GrentonActionScript,
        device_info: DeviceInfo | None = None,
    ) -> None:
        ButtonEntity.__init__(self)
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        self.script_action = script_action

    async def async_press(self, **kwargs: Any) -> None:
        """Plain button press: run the script with the value baked into the widget."""
        await self.coordinator.execute_action(self.script_action)

    async def run_with_parameter(self, parameter: str | None = None) -> None:
        """Run the script, overriding the widget's default value with ``parameter``.

        ``parameter`` is passed verbatim into the script call payload, so the user
        controls whether to pass a quoted Lua string (``"abc"``), a number (``42``),
        or no argument at all (empty string -> ``script()``).
        """
        action = self.script_action if parameter is None else replace(self.script_action, value=parameter)
        await self.coordinator.execute_action(action)
