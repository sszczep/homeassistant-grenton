"""Typed argument inputs for scene configuration and CLU script calls."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.helpers import selector

from ..enums import GrentonActionCallType
from ..scene_arguments import imported_arguments, normalize_arguments
from .configurable import (
    BaseGrentonEntityConfigurationSchema,
    StepDefinition,
    StepResult,
)


@selector.SELECTORS.register("grenton_arguments")
class GrentonArgumentsSelector(selector.Selector):
    """An inline, repeatable list of typed argument inputs."""

    selector_type = "grenton_arguments"
    CONFIG_SCHEMA = vol.Schema({})

    def __call__(self, data: Any) -> list[dict[str, Any]]:
        try:
            return normalize_arguments(data)
        except (TypeError, ValueError) as err:
            raise vol.Invalid(str(err)) from err


def scene_arguments_selector() -> GrentonArgumentsSelector:
    return GrentonArgumentsSelector({})


def validate_scene_action(data: dict[str, Any]) -> dict[str, Any]:
    """Validate only fields belonging to the selected call type."""
    config = {"call_type": data.get("call_type"), "clu_id": data.get("clu_id")}
    if not isinstance(config["call_type"], str) or config["call_type"] not in {
        item.value for item in GrentonActionCallType
    }:
        raise vol.Invalid("Select a call type", path=["call_type"])
    # Existing set values stay intact while configuring the action's target.
    value = data.get("value", "")
    if not isinstance(value, str):
        raise vol.Invalid("Value must be text", path=["value"])
    config["value"] = value
    if config["call_type"] == "VARIABLE":
        name = data.get("variable_name", data.get("index", ""))
        if not isinstance(name, str) or not name.strip():
            raise vol.Invalid("Enter a variable name", path=["variable_name"])
        config["variable_name"] = name.strip()
        return config
    name = data.get("object_name", "")
    if not isinstance(name, str) or not name.strip():
        raise vol.Invalid("Enter a script/object name", path=["object_name"])
    config["object_name"] = name.strip()
    if config["call_type"] != "SCRIPT":
        index = data.get("index", "")
        if not isinstance(index, str) or not index.strip():
            raise vol.Invalid("Enter an index", path=["index"])
        config["index"] = index.strip()
    if config["call_type"] in ("SCRIPT", "METHOD"):
        try:
            config["arguments"] = normalize_arguments(data.get("arguments", []))
        except (TypeError, ValueError) as err:
            raise vol.Invalid(str(err), path=["arguments"]) from err
    return config


@selector.SELECTORS.register("grenton_scene")
class GrentonSceneSelector(selector.Selector):
    """A scene form whose fields respond immediately to the call type."""

    selector_type = "grenton_scene"
    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Required("clus"): [{"value": str, "label": str}],
            vol.Optional("default_value", default=""): str,
            vol.Optional("mode", default="action"): vol.In(["action", "state"]),
            vol.Optional("editable_value", default=False): bool,
        }
    )

    def __call__(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise vol.Invalid("Scene action must be an object")
        if self.config["mode"] == "state" and data.get("call_type") not in (
            "ATTRIBUTE",
            "VARIABLE",
        ):
            raise vol.Invalid("Select Attribute or Variable", path=["call_type"])
        if not isinstance(data.get("clu_id"), str) or data["clu_id"] not in {
            clu["value"] for clu in self.config["clus"]
        }:
            raise vol.Invalid("Select a CLU", path=["clu_id"])
        config = validate_scene_action(
            {
                "value": self.config["default_value"],
                **data,
            }
        )
        if self.config["mode"] == "state":
            config.pop("value", None)
        return config


@dataclass
class GrentonEntitySceneConfigurationSchema(BaseGrentonEntityConfigurationSchema):
    """Use the Grenton editor inside the standard Home Assistant popup."""

    clu_options: list[dict[str, str]]

    @property
    def steps(self) -> list[StepDefinition]:
        return [StepDefinition("configure_scene_action", self._build_action)]

    def _build_action(
        self, current: dict[str, Any], accumulated: dict[str, Any]
    ) -> StepResult:
        # A rejected form includes the untouched editor draft, including invalid
        # rows. Do not normalize it until the next submission.
        submitted = current.get("action", current)
        draft = deepcopy(
            submitted
            if isinstance(submitted, dict)
            else {key: value for key, value in current.items() if key != "action"}
        )
        draft.setdefault("value", current.get("value", ""))
        draft.setdefault(
            "arguments", imported_arguments(draft.get("call_type", ""), draft["value"])
        )
        if draft.get("call_type") == "VARIABLE":
            draft.setdefault("variable_name", draft.get("index", ""))
        return StepResult(
            schema=vol.Schema(
                {
                    vol.Required(
                        "action", description={"suggested_value": draft}
                    ): GrentonSceneSelector(
                        {
                            "clus": self.clu_options,
                            "default_value": current.get("value", ""),
                        }
                    ),
                }
            ),
            validator=lambda data: data["action"],
        )
