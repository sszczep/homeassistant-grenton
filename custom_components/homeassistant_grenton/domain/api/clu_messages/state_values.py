"""Shared key encoding and value decoding for CLU state reads."""

from ....state import (
    GrentonCluStateAttributeKey,
    GrentonCluStateVariableKey,
    GrentonValue,
    cast_string_to_grenton_value,
)
from ...clu import GrentonClu
from ...device_types import attribute_index
from ...scene_arguments import quote_lua_string
from .report_values import split_report_values

StateKey = GrentonCluStateVariableKey | GrentonCluStateAttributeKey


def format_state_keys(keys: list[StateKey]) -> str:
    """Encode variable names and object/index pairs as one Lua table."""
    return (
        "{"
        + ",".join(
            quote_lua_string(key.name)
            if isinstance(key, GrentonCluStateVariableKey)
            else f"{{{key.object_name},{key.name}}}"
            for key in keys
        )
        + "}"
    )


def parse_state_values(
    payload: str,
    keys: list[StateKey] | None = None,
    clu: GrentonClu | None = None,
) -> list[GrentonValue]:
    """Decode a value table while preserving schedules and firmware strings."""
    if not (payload.startswith("{") and payload.endswith("}")):
        raise ValueError("Expected state values in braces")
    content = payload[1:-1].strip()
    if not content:
        return []

    raw_values = split_report_values(content, len(keys) if keys is not None else None)
    values: list[GrentonValue] = []
    for position, raw_value in enumerate(raw_values):
        token = raw_value.strip()
        quoted = len(token) >= 2 and token.startswith('"') and token.endswith('"')
        value = token[1:-1] if quoted else token
        key = keys[position] if keys is not None and position < len(keys) else None
        if (
            isinstance(key, GrentonCluStateAttributeKey)
            and clu is not None
            and key.object_name == clu.object_name
            and key.name == attribute_index(clu.device_type, "FirmwareVersion")
        ):
            # Versions are identifiers even when they look like numbers (1.20).
            values.append(None if value == "nil" else value)
        else:
            values.append(
                cast_string_to_grenton_value(value, preserve_string_whitespace=quoted)
            )
    return values
