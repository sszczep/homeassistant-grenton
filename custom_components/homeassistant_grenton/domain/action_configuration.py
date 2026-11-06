"""Convert editable action settings to and from imported Grenton actions."""

from typing import Any

from .action import (
    GrentonAction,
    GrentonActionAttribute,
    GrentonActionMethod,
    GrentonActionScript,
    GrentonActionVariable,
)
from .enums import GrentonActionCallType, GrentonActionEventType
from .scene_arguments import (
    argument_expressions,
    imported_arguments,
    normalize_arguments,
)

ACTION_CLASSES = {
    GrentonActionCallType.ATTRIBUTE: GrentonActionAttribute,
    GrentonActionCallType.METHOD: GrentonActionMethod,
    GrentonActionCallType.SCRIPT: GrentonActionScript,
    GrentonActionCallType.VARIABLE: GrentonActionVariable,
}


def action_configuration(action: GrentonAction) -> dict[str, Any]:
    call_type = next(
        key for key, cls in ACTION_CLASSES.items() if isinstance(action, cls)
    )
    config = {
        "call_type": call_type.value,
        "clu_id": action.clu_id,
        "object_name": action.object_name,
        "value": action.value,
    }
    if isinstance(action, GrentonActionVariable):
        config["variable_name"] = action.index
        config.pop("object_name")
    elif isinstance(action, (GrentonActionAttribute, GrentonActionMethod)):
        config["index"] = action.index
    if isinstance(action, GrentonActionMethod) and action.arguments is not None:
        config["arguments"] = imported_arguments("SCRIPT", ", ".join(action.arguments))
    return config


def normalize_action_configuration(config: dict[str, Any]) -> dict[str, Any]:
    config = {**config, "value": config.get("value", "")}
    call_type = config["call_type"]
    if call_type in ("SCRIPT", "METHOD"):
        if "arguments" in config:
            config["arguments"] = normalize_arguments(config["arguments"])
            config["value"] = ", ".join(argument_expressions(config["arguments"]))
    else:
        config.pop("arguments", None)
    if call_type == "SCRIPT":
        config.pop("index", None)
    if call_type == "VARIABLE":
        config["variable_name"] = config.get("variable_name", config.get("index", ""))
        config.pop("index", None)
        config.pop("object_name", None)
    else:
        config.pop("variable_name", None)
    return config


def configured_action(
    config: dict[str, Any], event: GrentonActionEventType
) -> GrentonAction:
    config = normalize_action_configuration(config)
    call_type = GrentonActionCallType(config["call_type"])
    fields = {
        "clu_id": config["clu_id"],
        "object_name": config.get("object_name", ""),
        "event": event,
        "value": config["value"],
    }
    if "arguments" in config and call_type == GrentonActionCallType.METHOD:
        fields["arguments"] = argument_expressions(config["arguments"])
    if call_type == GrentonActionCallType.VARIABLE:
        fields["index"] = config["variable_name"]
    elif call_type != GrentonActionCallType.SCRIPT:
        fields["index"] = config["index"]
    return ACTION_CLASSES[call_type](**fields)


def action_editor_draft(config: dict[str, Any]) -> dict[str, Any]:
    """Fill argument rows without changing the imported wire representation."""
    config = dict(config)
    if config.get("call_type") in ("SCRIPT", "METHOD"):
        value = config.get("value", "")
        config.setdefault(
            "arguments",
            imported_arguments(config["call_type"], value)
            if isinstance(value, str)
            else [],
        )
    return config
