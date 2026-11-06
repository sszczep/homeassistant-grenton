"""Gate HTTP transport.

Talks to a Grenton GATE HTTP module through an HttpListener whose OnRequest
script evaluates every JSON value as Lua and returns the results under the
same keys. The wire format is compatible with the listener script used by
the "Grenton Objects" integration (HA_Integration_Listener):

    request:  {"status": "return 1", "s0": "return CLU1:execute(0, \"DOU1:get(0)\")"}
    response: {"g_status": "OK", "status": 1, "s0": 1}

The coordinator exposes the same interface as the UDP coordinator
(register_component_state / get_value_for_component / execute_action), so
the existing entity classes work unchanged on either transport.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .domain.action import GrentonAction
from .domain.api.clu_messages import GrentonCluApiActionRequest
from .domain.state_object import (
    GrentonAttributeValueObject,
    GrentonStateObject,
    GrentonVariableValueObject,
)
from .state import GrentonValue

_LOGGER = logging.getLogger(__name__)

CONF_GATE = "gate"
CONF_GATE_URL = "url"
CONF_GATE_SCAN_INTERVAL = "scan_interval"
CONF_GATE_WEBHOOK_ID = "webhook_id"
DEFAULT_SCAN_INTERVAL = 10
REQUEST_TIMEOUT = 10
# Keys evaluated per HTTP request; keeps a single Lua run on the Gate short.
READ_CHUNK_SIZE = 25
# The listener script only runs when "command" or "status" is present.
_SENTINEL = {"status": "return 1"}


def lua_string(text: str) -> str:
    """Quote text as a Lua string literal."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def remote_lua(clu: str, lua: str, returns: bool = False) -> str:
    """Lua run on the Gate that executes `lua` on the given CLU."""
    call = f"{clu}:execute(0, {lua_string(lua)})"
    return f"return {call}" if returns else call


def state_read_lua(state: GrentonStateObject) -> str:
    if isinstance(state, GrentonVariableValueObject):
        return remote_lua(state.clu_id, f'getVar("{state.index}")', returns=True)
    return remote_lua(state.clu_id, f"{state.object_name}:get({state.index})", returns=True)


def _state_key(state: GrentonStateObject) -> tuple[str, str, str, str]:
    return (type(state).__name__, state.clu_id, state.object_name, str(state.index))


class GrentonGateError(Exception):
    pass


class GrentonGateClient:
    def __init__(self, hass: HomeAssistant, url: str) -> None:
        self._session = async_get_clientsession(hass)
        self.url = url

    async def call(self, payload: dict[str, str]) -> dict[str, Any]:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                # GET with a JSON body, as expected by the listener setup.
                async with self._session.get(self.url, json=payload) as response:
                    if response.status != 200:
                        raise GrentonGateError(f"HTTP {response.status}")
                    data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise GrentonGateError(str(err)) from err
        if not isinstance(data, dict) or data.get("g_status") != "OK":
            raise GrentonGateError(f"Unexpected response: {data!r}")
        return data

    async def test(self) -> None:
        await self.call(dict(_SENTINEL))


class GrentonGateCoordinator(DataUpdateCoordinator[dict[tuple[str, str, str, str], GrentonValue]]):
    """Polls all registered states in batches and executes actions."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, url: str, scan_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="grenton_gate",
            update_interval=timedelta(seconds=max(2, int(scan_interval))),
        )
        self.config_entry = config_entry
        self.client = GrentonGateClient(hass, url)
        self._states: dict[tuple[str, str, str, str], GrentonStateObject] = {}
        self.data = {}

    # --- interface shared with GrentonCoordinator -------------------------
    def register_component_state(self, state: GrentonStateObject) -> None:
        self._states[_state_key(state)] = state

    def get_value_for_component(self, state: GrentonStateObject) -> GrentonValue | None:
        return (self.data or {}).get(_state_key(state))

    async def execute_action(self, action: GrentonAction) -> None:
        lua = GrentonCluApiActionRequest.from_action(action).payload
        try:
            await self.client.call({"command": remote_lua(action.clu_id, lua)})
        except GrentonGateError as err:
            _LOGGER.error("[gate] Action %s failed: %s", lua, err)
            return
        await self.async_request_refresh()

    # --- push (webhook) ----------------------------------------------------
    def push_updates(self, updates: list[dict[str, Any]]) -> int:
        """Apply values pushed by the Gate; returns the number of known keys updated.

        Accepted items:
            {"clu": "CLU1", "object": "DOU1", "index": 0, "value": 1}
            {"id": "CLU1->DOU1", "index": 0, "value": 1}
            {"clu": "CLU1", "variable": "feature", "value": 21.5}
        """
        data = dict(self.data or {})
        applied = 0
        for item in updates:
            if not isinstance(item, dict) or "value" not in item:
                continue
            clu, obj = item.get("clu"), item.get("object")
            if item.get("id") and "->" in str(item["id"]):
                clu, obj = (part.strip() for part in str(item["id"]).split("->", 1))
            if not clu:
                continue
            if item.get("variable"):
                name = str(item["variable"])
                key = _state_key(GrentonVariableValueObject(clu_id=str(clu), object_name=name, index=name))
            elif obj is not None:
                key = _state_key(GrentonAttributeValueObject(
                    clu_id=str(clu), object_name=str(obj), index=str(item.get("index", 0))))
            else:
                continue
            if key in self._states:
                data[key] = item["value"]
                applied += 1
        if applied:
            self.async_set_updated_data(data)
        return applied

    # --- polling ------------------------------------------------------------
    async def _async_update_data(self) -> dict[tuple[str, str, str, str], GrentonValue]:
        result: dict[tuple[str, str, str, str], GrentonValue] = {}
        items = list(self._states.items())
        for start in range(0, len(items), READ_CHUNK_SIZE):
            chunk = items[start:start + READ_CHUNK_SIZE]
            payload = dict(_SENTINEL)
            for i, (_, state) in enumerate(chunk):
                payload[f"s{i}"] = state_read_lua(state)
            try:
                data = await self.client.call(payload)
            except GrentonGateError as err:
                raise UpdateFailed(f"Gate HTTP unreachable: {err}") from err
            for i, (key, _) in enumerate(chunk):
                result[key] = data.get(f"s{i}")
        return result
