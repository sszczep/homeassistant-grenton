"""Configurable DIMMER_V2 lights with parameterized brightness commands."""

from copy import deepcopy
from dataclasses import dataclass, replace
from math import isfinite
from typing import Any

import voluptuous as vol
from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import DeviceInfo

from ...coordinator import GrentonCoordinator
from ..action import GrentonAction, GrentonActionMethod
from ..action_configuration import (
    action_configuration,
    configured_action,
    normalize_action_configuration,
)
from ..entity_references import action_reference
from ..state_object import (
    GrentonAttributeValueObject,
    GrentonStateObject,
    GrentonVariableValueObject,
)
from ..utils.ranges import map_range
from ..utils.values import format_action_value
from .base import BaseGrentonEntity
from .configurable import ConfigurableEntity, StepDefinition, StepResult
from .on_off import GrentonOnOffConfigurationSchema


def validate_range(config: dict[str, Any]) -> dict[str, Any]:
    """Reject unusable brightness ranges before saving them."""
    for key in ("min", "max", "precision"):
        value = config[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
        ):
            raise vol.Invalid("Enter a finite number", path=[key])
    if config["max"] <= config["min"]:
        raise vol.Invalid("Maximum must exceed minimum", path=["max"])
    if (
        not 0 <= config["precision"] <= 6
        or int(config["precision"]) != config["precision"]
    ):
        raise vol.Invalid(
            "Precision must be a whole number from 0 to 6", path=["precision"]
        )
    return {**config, "precision": int(config["precision"])}


def validate_brightness_action(config: dict[str, Any]) -> dict[str, Any]:
    """Require the brightness parameter so every level can be selected."""
    action = normalize_action_configuration(config["action_set_value"])
    if "$value$" not in action["value"]:
        raise vol.Invalid(
            "Include $value$ in the brightness action", path=["action_set_value"]
        )
    return {**config, "action_set_value": action}


@dataclass
class GrentonDimmerConfigurationSchema(GrentonOnOffConfigurationSchema):
    """Reuse the state/action editors without changing the light's domain."""

    @property
    def steps(self) -> list[StepDefinition]:
        return [
            StepDefinition("configure_dimmer_state", self._build_state),
            StepDefinition("configure_dimmer_on_action", self._build_on_action),
            StepDefinition("configure_dimmer_off_action", self._build_off_action),
            StepDefinition(
                "configure_dimmer_brightness_action", self._build_brightness_action
            ),
        ]

    def _build_state(self, current, accumulated) -> StepResult:
        marker, editor = self._editor("state", current, state=True)
        fields = {marker: editor}
        for key in ("min", "max", "precision"):
            fields[vol.Required(key, default=current[key])] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    **(
                        {"min": 0, "max": 6, "step": 1}
                        if key == "precision"
                        else {"step": "any"}
                    ),
                    mode=selector.NumberSelectorMode.BOX,
                )
            )
        return StepResult(schema=vol.Schema(fields), validator=validate_range)

    def _build_brightness_action(self, current, accumulated) -> StepResult:
        marker, editor = self._editor("action_set_value", current)
        return StepResult(
            schema=vol.Schema({marker: editor}), validator=validate_brightness_action
        )


class GrentonEntityDimmer(  # type: ignore[misc]  # HA's nullable unique_id vs ConfigurableEntity.
    BaseGrentonEntity, LightEntity, ConfigurableEntity[GrentonDimmerConfigurationSchema]
):
    """Dimmer light with independent state, ON, OFF and brightness bindings."""

    reload_after_configuration = True
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
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._widget_range = {"min": min, "max": max, "precision": precision}
        self._widget_state = state_object
        self._widget_actions = {
            "action_on": action_on,
            "action_off": action_off,
            "action_set_value": action_set_value,
        }
        clu_options = [
            {"value": clu.id, "label": f"{clu.name} ({clu.id})"}
            for clu in coordinator.clus
        ]
        ConfigurableEntity.__init__(self, clu_options=clu_options)
        self._config = {**self.default_config(), **deepcopy(self._config)}
        for key in ("state", *self._widget_actions):
            clu_id = self._config[key]["clu_id"]
            if clu_id not in {option["value"] for option in clu_options}:
                clu_options.append({"value": clu_id, "label": clu_id})
        coordinator.register_component_state(self.state_object)

    def default_config(self) -> dict[str, Any]:
        return {
            **self._widget_range,
            "state": self._widget_state.source_attributes,
            **{
                key: action_configuration(action)
                for key, action in self._widget_actions.items()
            },
        }

    @property
    def min(self) -> float:
        return self._config["min"]

    @property
    def max(self) -> float:
        return self._config["max"]

    @property
    def precision(self) -> int:
        return self._config["precision"]

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

    def _action(self, key: str) -> GrentonAction:
        return configured_action(self._config[key], self._widget_actions[key].event)

    @property
    def action_on(self) -> GrentonAction:
        return self._action("action_on")

    @property
    def action_off(self) -> GrentonAction:
        return self._action("action_off")

    @property
    def action_set_value(self) -> GrentonAction:
        return self._action("action_set_value")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = {
            **(super().extra_state_attributes or {}),
            "brightness_range": {
                "min": self.min,
                "max": self.max,
                "precision": self.precision,
            },
        }
        for key in self._widget_actions:
            attributes.update(action_reference(self._action(key), prefix=f"{key}_"))
        return attributes

    async def apply_configuration(self, user_input: dict[str, Any]) -> dict[str, Any]:
        config = validate_range({**self._config, **deepcopy(user_input)})
        config = validate_brightness_action(config)
        for key in self._widget_actions:
            config[key] = normalize_action_configuration(config[key])
        return await super().apply_configuration(config)

    def _native_value(self) -> float | None:
        value = self.coordinator.get_value_for_component(self.state_object)
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if isfinite(value) else None

    @property
    def is_on(self) -> bool | None:
        value = self._native_value()
        return value > 0 if value is not None else None

    @property
    def brightness(self) -> int | None:
        value = self._native_value()
        if value is None:
            return None
        return max(0, min(255, int(map_range((self.min, self.max), (0, 255), value))))

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS not in kwargs:
            await self.coordinator.execute_action(self.action_on)
            return
        brightness = kwargs[ATTR_BRIGHTNESS]
        if (
            isinstance(brightness, bool)
            or not isinstance(brightness, (int, float))
            or not isfinite(brightness)
            or not 0 <= brightness <= 255
        ):
            raise ServiceValidationError("Brightness must be between 0 and 255")
        if brightness == 0:
            await self.async_turn_off()
            return
        # "2", not "2.0", for precision-0 channels (upstream PR #15)
        value = format_action_value(
            map_range((0, 255), (self.min, self.max), brightness), self.precision
        )
        template = self.action_set_value
        # Preserve fixed script parameters and never mutate the imported template.
        action = replace(template, value=template.value.replace("$value$", value))
        if isinstance(action, GrentonActionMethod) and action.arguments is not None:
            action = replace(
                action,
                arguments=tuple(
                    arg.replace("$value$", value) for arg in action.arguments
                ),
            )
        await self.coordinator.execute_action(action)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.execute_action(self.action_off)
