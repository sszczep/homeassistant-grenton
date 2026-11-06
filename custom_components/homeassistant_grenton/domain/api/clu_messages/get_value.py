"""Direct attribute reads observed in the official Object Manager."""

import re

from ....state import (
    GrentonCluStateAttributeKey,
    GrentonValue,
    cast_string_to_grenton_value,
)
from ...clu import GrentonClu
from ...device_types import attribute_index
from .base import GrentonCluApiRequest, GrentonCluApiResponse
from .state_values import StateKey

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


class GrentonCluApiGetValueRequest(GrentonCluApiRequest):
    """Read one attribute without creating a notification registration."""

    def __init__(
        self, key: GrentonCluStateAttributeKey, msg_id: str | None = None
    ) -> None:
        if not isinstance(key, GrentonCluStateAttributeKey):
            raise TypeError("Direct reads require an attribute key")
        if not isinstance(key.object_name, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", key.object_name
        ):
            raise ValueError("Direct reads require a Lua object identifier")
        if not isinstance(key.name, str) or not re.fullmatch(r"[0-9]+", key.name):
            raise ValueError("Direct reads require a nonnegative attribute index")
        self.key = key
        self.keys: list[StateKey] = [key]
        super().__init__(f"{key.object_name}:get({key.name})", msg_id)


class GrentonCluApiGetValueResponse(GrentonCluApiResponse):
    """Decode the raw scalar body returned by a direct attribute read.

    Object Manager schedule replies have no value prefix, braces, or quotes.
    Commas, braces, quotes and edge spaces therefore belong to the value itself.
    Only exact primitive tokens are converted; other bodies remain verbatim.
    """

    def __init__(
        self,
        wire_message: str,
        key: GrentonCluStateAttributeKey,
        clu: GrentonClu | None = None,
    ) -> None:
        try:
            super().__init__(wire_message)
        except ValueError:
            raise ValueError("Invalid direct attribute response envelope") from None

        value: GrentonValue = self.payload
        firmware = (
            clu is not None
            and key.object_name == clu.object_name
            and key.name == attribute_index(clu.device_type, "FirmwareVersion")
        )
        if self.payload == "nil":
            value = None
        elif not firmware and (
            self.payload in ("true", "false") or _NUMBER.fullmatch(self.payload)
        ):
            value = cast_string_to_grenton_value(self.payload)
        self.values: list[GrentonValue] = [value]
