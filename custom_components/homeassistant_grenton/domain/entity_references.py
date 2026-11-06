"""Compact Grenton references for entity state, separate from editor settings."""

from typing import Any

from .action import (
    GrentonAction,
    GrentonActionAttribute,
    GrentonActionMethod,
    GrentonActionScript,
    GrentonActionVariable,
)
from .lua_arguments import imported_lua_argument, split_lua_arguments
from .state_object import GrentonStateObject, GrentonVariableValueObject


def _object_reference(object_name: str, index: str) -> str:
    return f"{object_name}.{index}" if object_name else index


def state_reference(state: GrentonStateObject) -> dict[str, str]:
    """Describe a source without exposing its persisted configuration fields."""
    return {
        "clu_id": state.clu_id,
        "call_type": "VARIABLE"
        if isinstance(state, GrentonVariableValueObject)
        else "ATTRIBUTE",
        "object": _object_reference(state.object_name, state.index),
    }


def _argument_value(expression: str) -> Any:
    argument = imported_lua_argument(expression.strip())
    return expression if argument["type"] == "lua" else argument["value"]


def action_reference(action: GrentonAction, prefix: str = "") -> dict[str, Any]:
    """Show effective targets and real call arguments, without editor metadata."""
    if isinstance(action, GrentonActionVariable):
        call_type = "VARIABLE"
        target = _object_reference(action.object_name, action.index)
    elif isinstance(action, GrentonActionAttribute):
        call_type = "ATTRIBUTE"
        target = _object_reference(action.object_name, action.index)
    elif isinstance(action, GrentonActionMethod):
        call_type = "METHOD"
        target = _object_reference(action.object_name, action.index)
    elif isinstance(action, GrentonActionScript):
        call_type = "SCRIPT"
        target = action.object_name
    else:
        raise TypeError(f"Unsupported action type: {type(action).__name__}")

    attributes: dict[str, Any] = {
        f"{prefix}clu_id": action.clu_id,
        f"{prefix}call_type": call_type,
        f"{prefix}object": target,
    }
    if isinstance(action, GrentonActionMethod):
        # Imported methods pass one quoted string, even when it contains commas.
        attributes[f"{prefix}args"] = (
            [action.value]
            if action.arguments is None
            else [_argument_value(expression) for expression in action.arguments]
        )
    elif isinstance(action, GrentonActionScript):
        attributes[f"{prefix}args"] = [
            _argument_value(expression)
            for expression in split_lua_arguments(action.value)
        ]
    return attributes
