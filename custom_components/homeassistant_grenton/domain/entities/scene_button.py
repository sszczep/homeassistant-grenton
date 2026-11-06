from dataclasses import replace
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo

from ...coordinator import GrentonCoordinator
from ..action import GrentonAction, GrentonActionMethod
from ..action_configuration import (
    action_configuration,
    configured_action,
    normalize_action_configuration,
)
from ..entity_references import action_reference
from .base import BaseGrentonEntity
from .configurable import ConfigurableEntity
from .scene_configuration import GrentonEntitySceneConfigurationSchema


class GrentonEntitySceneButton(  # pyright: ignore[reportIncompatibleVariableOverride]
    BaseGrentonEntity,
    ConfigurableEntity[GrentonEntitySceneConfigurationSchema],
    ButtonEntity,
):
    """Scene button with an inspectable, configurable Grenton action."""

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        script_action: GrentonAction,
        device_info: DeviceInfo | None = None,
    ) -> None:
        ButtonEntity.__init__(self)
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        self._widget_action = script_action
        clu_options = [
            {"value": clu.id, "label": f"{clu.name} ({clu.id})"}
            for clu in coordinator.clus
        ]
        ConfigurableEntity.__init__(self, clu_options=clu_options)
        loaded = self._config
        self._config = {**self.default_config(), **loaded}
        if self._config["call_type"] == "VARIABLE":
            # Migrate the old variable "index" to its actual string name.
            self._config["variable_name"] = loaded.get(
                "variable_name",
                loaded.get("index", self._config.get("variable_name", "")),
            )
            self._config.pop("index", None)
            self._config.pop("object_name", None)
        else:
            self._config.pop("variable_name", None)
        if self._config["call_type"] == "SCRIPT":
            self._config.pop("index", None)
        for clu_id in {script_action.clu_id, self._config["clu_id"]}:
            if clu_id not in {option["value"] for option in clu_options}:
                clu_options.append({"value": clu_id, "label": clu_id})

    def default_config(self) -> dict[str, Any]:
        return action_configuration(self._widget_action)

    @property
    def script_action(self) -> GrentonAction:
        """Effective action, including saved Home Assistant overrides."""
        return configured_action(self._config, self._widget_action.event)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose only the effective action reference and its argument values."""
        return action_reference(self.script_action)

    async def apply_configuration(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Apply immediately and return options to persist without a reload."""
        config = normalize_action_configuration(user_input)
        options = await super().apply_configuration(config)
        if self.hass is not None and self.entity_id is not None:
            self.async_write_ha_state()
        return options

    async def async_press(self, **kwargs: Any) -> None:
        """Run the scene with its configured arguments/value."""
        await self.coordinator.execute_action(self.script_action)

    async def run_with_parameter(self, parameter: str | None = None) -> None:
        """Apply an upstream-compatible, per-call raw Lua parameter override."""
        action = self.script_action
        if parameter is not None:
            action = replace(action, value=parameter)
            if isinstance(action, GrentonActionMethod):
                # Typed method arguments otherwise take precedence over value.
                action = replace(action, arguments=(parameter,) if parameter else ())
        await self.coordinator.execute_action(action)
