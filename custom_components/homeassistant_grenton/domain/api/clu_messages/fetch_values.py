"""One-off state reads used by the official myGrenton application."""

from ...clu import GrentonClu
from .base import GrentonCluApiRequest, GrentonCluApiResponse
from .state_values import StateKey, format_state_keys, parse_state_values


class GrentonCluApiFetchValuesRequest(GrentonCluApiRequest):
    """Fetch current values without registering a notification group."""

    def __init__(self, keys: list[StateKey], msg_id: str | None = None):
        if not keys:
            raise ValueError("Cannot fetch values without keys")
        self.keys = keys
        super().__init__(f"SYSTEM:fetchValues({format_state_keys(keys)})", msg_id)


class GrentonCluApiFetchValuesResponse(GrentonCluApiResponse):
    """Decode the values table returned by a fetchValues request."""

    def __init__(
        self,
        wire_message: str,
        keys: list[StateKey],
        clu: GrentonClu | None = None,
    ):
        try:
            super().__init__(wire_message)
        except ValueError:
            # Malformed packet diagnostics must not copy returned device values.
            raise ValueError("Invalid fetchValues response envelope") from None
        if not self.payload.startswith("values:"):
            raise ValueError("Expected a values response")
        self.values = parse_state_values(self.payload[len("values:") :], keys, clu)
