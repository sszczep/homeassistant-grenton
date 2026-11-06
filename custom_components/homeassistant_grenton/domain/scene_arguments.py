"""Typed scene arguments and their Lua wire representation."""

import math
from typing import Any

from .lua_arguments import imported_lua_argument, split_lua_arguments

ARGUMENT_TYPES = ("string", "number", "float", "boolean", "nil", "lua")


def normalize_arguments(arguments: Any) -> list[dict[str, Any]]:
    """Accept persisted arguments or rows from the native argument editor."""
    if not isinstance(arguments, list):
        raise TypeError("Arguments must be a list")
    normalized = []
    for position, row in enumerate(arguments, start=1):
        if not isinstance(row, dict):
            raise TypeError(f"Argument {position} must have a type and value")
        if "argument" in row:
            choice = row["argument"]
            if not isinstance(choice, dict):
                raise ValueError(f"Argument {position} must have a selected type")
            argument_type = choice.get("active_choice")
            if argument_type not in ARGUMENT_TYPES or argument_type not in choice:
                raise ValueError(
                    f"Argument {position} must have a valid type and value"
                )
            value = choice[argument_type]
        else:
            argument_type = row.get("type")
            value = row.get("value")
        if argument_type not in ARGUMENT_TYPES:
            raise ValueError(f"Argument {position} has an invalid type")
        if argument_type in ("string", "lua"):
            if not isinstance(value, str) or (
                argument_type == "lua" and not value.strip()
            ):
                raise ValueError(f"Argument {position} must contain text")
        elif argument_type in ("number", "float"):
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError(f"Argument {position} must be a number")
            try:
                value = (
                    value
                    if argument_type == "number" and isinstance(value, int)
                    else float(value)
                )
            except (ValueError, OverflowError) as err:
                raise ValueError(f"Argument {position} must be a number") from err
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"Argument {position} must be a finite number")
            if (
                argument_type == "number"
                and isinstance(value, float)
                and value.is_integer()
            ):
                value = int(value)
        elif argument_type == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"Argument {position} must be true or false")
        else:
            if value is not None and value != "nil":
                raise ValueError(f"Argument {position} must be nil")
            value = None
        normalized.append({"type": argument_type, "value": value})
    return normalized


def quote_lua_string(value: str) -> str:
    """Quote a string without letting its contents become Lua expressions."""
    escapes = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t"}
    escaped = "".join(
        escapes.get(
            char, f"\\{ord(char):03d}" if ord(char) < 32 or ord(char) == 127 else char
        )
        for char in value
    )
    return f'"{escaped}"'


def argument_expressions(arguments: Any) -> tuple[str, ...]:
    """Render each typed argument separately, in the configured order."""
    expressions = []
    for argument in normalize_arguments(arguments):
        argument_type, value = argument["type"], argument["value"]
        if argument_type == "string":
            expression = quote_lua_string(value)
        elif argument_type == "boolean":
            expression = "true" if value else "false"
        elif argument_type == "nil":
            expression = "nil"
        else:
            expression = str(value)
        expressions.append(expression)
    return tuple(expressions)


def imported_arguments(call_type: str, value: str) -> list[dict[str, Any]]:
    """Expose each imported script or method argument with its inferred type."""
    if call_type in ("SCRIPT", "METHOD"):
        return [imported_lua_argument(part) for part in split_lua_arguments(value)]
    return []


def arguments_to_ui(arguments: Any) -> list[dict[str, Any]]:
    """Restore the type picker and its selected input for every argument row."""
    return [
        {
            "argument": {
                "active_choice": item["type"],
                item["type"]: "nil" if item["type"] == "nil" else item["value"],
            }
        }
        for item in normalize_arguments(arguments)
    ]
