"""Configurable state, actions and switch/light presentation for ON_OFF."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, ClassVar
from unicodedata import combining, normalize

import voluptuous as vol
from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import DeviceInfo

from ...coordinator import GrentonCoordinator
from ..action import GrentonAction
from ..action_configuration import (
    action_configuration,
    action_editor_draft,
    configured_action,
    normalize_action_configuration,
)
from ..entity_references import action_reference
from ..enums import GrentonUnit
from ..state_object import (
    GrentonAttributeValueObject,
    GrentonStateObject,
    GrentonVariableValueObject,
)
from .base import BaseGrentonEntity
from .configurable import (
    BaseGrentonEntityConfigurationSchema,
    ConfigurableEntity,
    StepDefinition,
    StepResult,
)
from .scene_configuration import GrentonSceneSelector


@dataclass
class GrentonOnOffConfigurationSchema(BaseGrentonEntityConfigurationSchema):
    clu_options: list[dict[str, str]]

    @property
    def steps(self) -> list[StepDefinition]:
        return [
            StepDefinition("configure_on_off_state", self._build_state),
            StepDefinition("configure_on_off_on_action", self._build_on_action),
            StepDefinition("configure_on_off_off_action", self._build_off_action),
        ]

    def _editor(self, key: str, current: dict[str, Any], *, state: bool = False):
        submitted = current.get(key)
        draft = deepcopy(submitted) if isinstance(submitted, dict) else {}
        if not state:
            draft = action_editor_draft(draft)
        return (
            vol.Required(key, description={"suggested_value": draft}),
            GrentonSceneSelector(
                {
                    "clus": self.clu_options,
                    "mode": "state" if state else "action",
                    "editable_value": not state,
                    "default_value": draft.get("value", "")
                    if isinstance(draft.get("value", ""), str)
                    else "",
                }
            ),
        )

    def _build_state(
        self, current: dict[str, Any], accumulated: dict[str, Any]
    ) -> StepResult:
        marker, editor = self._editor("state", current, state=True)
        return StepResult(
            schema=vol.Schema(
                {
                    vol.Required(
                        "entity_type", default=current.get("entity_type", "switch")
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["switch", "light"],
                            translation_key="on_off_entity_types",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    marker: editor,
                }
            )
        )

    def _build_on_action(self, current, accumulated) -> StepResult:
        marker, editor = self._editor("action_on", current)
        return StepResult(schema=vol.Schema({marker: editor}))

    def _build_off_action(self, current, accumulated) -> StepResult:
        marker, editor = self._editor("action_off", current)
        return StepResult(schema=vol.Schema({marker: editor}))


def configured_on_off_type(
    coordinator: GrentonCoordinator,
    unique_id: str,
    *,
    label: str = "",
    icon: str | None = None,
) -> str:
    """Prefer saved choices; otherwise detect lights from imported metadata."""
    config = coordinator.config_entry.options.get("entities", {}).get(unique_id, {})
    if config.get("entity_type") in ("switch", "light"):
        return config["entity_type"]
    name = "".join(
        character
        for character in normalize("NFKD", label.casefold().replace("ł", "l"))
        if not combining(character)
    )
    return (
        "light"
        if "light" in name
        or "swiatlo" in name
        or (icon or "").strip().casefold() == "bulb"
        else "switch"
    )


class GrentonEntityOnOff(
    BaseGrentonEntity, ConfigurableEntity[GrentonOnOffConfigurationSchema]
):
    """Share state, actions and options between the switch and light domains."""

    reload_after_configuration = True
    default_entity_type: ClassVar[str] = "switch"

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
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        self.unit = unit
        self._widget_state = state_object
        self._widget_action_on = action_on
        self._widget_action_off = action_off
        clu_options = [
            {"value": clu.id, "label": f"{clu.name} ({clu.id})"}
            for clu in coordinator.clus
        ]
        ConfigurableEntity.__init__(self, clu_options=clu_options)
        self._config = {**self.default_config(), **deepcopy(self._config)}
        for key in ("state", "action_on", "action_off"):
            clu_id = self._config[key]["clu_id"]
            if clu_id not in {option["value"] for option in clu_options}:
                clu_options.append({"value": clu_id, "label": clu_id})
        # Register the effective source on reload, including saved overrides.
        coordinator.register_component_state(self.state_object)

    def default_config(self) -> dict[str, Any]:
        state = self._widget_state
        state_config = {"call_type": state.call_type, "clu_id": state.clu_id}
        if isinstance(state, GrentonVariableValueObject):
            state_config["variable_name"] = state.index
        else:
            state_config.update(object_name=state.object_name, index=state.index)
        return {
            "entity_type": self.default_entity_type,
            "state": state_config,
            "action_on": action_configuration(self._widget_action_on),
            "action_off": action_configuration(self._widget_action_off),
        }

    @property
    def state_object(self) -> GrentonStateObject:
        config = self._config["state"]
        if config["call_type"] == "VARIABLE":
            return GrentonVariableValueObject(
                config["clu_id"], "", config["variable_name"]
            )
        return GrentonAttributeValueObject(
            config["clu_id"], config["object_name"], config["index"]
        )

    @property
    def action_on(self) -> GrentonAction:
        return configured_action(
            self._config["action_on"], self._widget_action_on.event
        )

    @property
    def action_off(self) -> GrentonAction:
        return configured_action(
            self._config["action_off"], self._widget_action_off.event
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = dict(super().extra_state_attributes or {})
        for key, action in (
            ("action_on", self.action_on),
            ("action_off", self.action_off),
        ):
            attributes.update(action_reference(action, prefix=f"{key}_"))
        return attributes

    async def apply_configuration(self, user_input: dict[str, Any]) -> dict[str, Any]:
        config = {**self._config, **deepcopy(user_input)}
        for key in ("action_on", "action_off"):
            config[key] = normalize_action_configuration(config[key])
        return await super().apply_configuration(config)

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.get_value_for_component(self.state_object)
        if value is None:
            return None
        return value == "ON" or value == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.execute_action(self.action_on)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.execute_action(self.action_off)


class GrentonEntityOnOffLight(GrentonEntityOnOff, LightEntity):
    """An ON_OFF control exposed as a light without dimming capabilities."""

    default_entity_type = "light"
    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF
