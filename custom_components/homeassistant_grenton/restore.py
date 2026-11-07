"""Restore lights after a CLU restart (e.g. after a power failure).

How it works
- Every state change of a Grenton light is recorded with its timestamp
  (on/off, brightness, colour) in a Home Assistant Store, so the history
  survives a Home Assistant restart too (CLU and HA often lose power together).
- The CLU boot time is derived from its Uptime sensor (boot = now - uptime) and
  stored per CLU. A boot time later than the stored one means the CLU restarted.
- After a restart, each light of that CLU is set back to its last state recorded
  *before* the boot time. Lights already in that state are left alone, and a
  short network loss (no restart) never triggers anything.
- When a light comes back from "unavailable", the CLU's slow values (Uptime
  included) are read at once, so a restart is noticed within seconds.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_HS_COLOR, ATTR_RGB_COLOR, LightEntity
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

CONF_RESTORE_LIGHTS = "restore_lights"   # options: {"enabled": bool, "exclude": [entity_id]}
STORE_VERSION = 1
HISTORY_PER_LIGHT = 6
# Boot times closer than this are the same boot (uptime/poll jitter)
BOOT_TOLERANCE = timedelta(seconds=90)
SAVE_DELAY = 5


def _snapshot(state: Any) -> dict[str, Any] | None:
    if state is None or state.state not in (STATE_ON, STATE_OFF):
        return None
    snap: dict[str, Any] = {"on": state.state == STATE_ON}
    if snap["on"]:
        attributes = state.attributes
        if attributes.get(ATTR_BRIGHTNESS) is not None:
            snap["brightness"] = int(attributes[ATTR_BRIGHTNESS])
        if attributes.get(ATTR_HS_COLOR) is not None:
            snap["hs_color"] = list(attributes[ATTR_HS_COLOR])
        elif attributes.get(ATTR_RGB_COLOR) is not None:
            snap["rgb_color"] = list(attributes[ATTR_RGB_COLOR])
    return snap


def _same(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    if a is None or b is None:
        return False
    if a["on"] != b["on"]:
        return False
    if not a["on"]:
        return True
    if abs(int(a.get("brightness", 0)) - int(b.get("brightness", 0))) > 3:
        return False
    for key in ("hs_color", "rgb_color"):
        if key in a and key in b and any(abs(float(x) - float(y)) > 2 for x, y in zip(a[key], b[key])):
            return False
    return True


class LightRestoreManager:
    def __init__(
        self,
        hass: HomeAssistant,
        entry: Any,
        coordinator: Any,
        lights: list[LightEntity],
        uptime_entities: dict[str, Any],
        exclude: set[str],
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self._lights = lights
        self._uptime_entities = uptime_entities
        self._exclude = exclude
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, f"grenton.restore_lights.{entry.entry_id}")
        self._data: dict[str, Any] = {"boot": {}, "lights": {}}
        self._unsubscribe: list[Any] = []
        self._light_clu: dict[str, str] = {}      # entity_id -> clu_id
        self._light_uid: dict[str, str] = {}      # entity_id -> unique_id
        self._uptime_clu: dict[str, str] = {}     # uptime entity_id -> clu_id
        self._pending_polls: dict[str, Any] = {}

    async def async_start(self) -> None:
        self._data = await self._store.async_load() or {"boot": {}, "lights": {}}
        self._data.setdefault("boot", {})
        self._data.setdefault("lights", {})
        for light in self._lights:
            entity_id = light.entity_id
            sources = getattr(light, "state_sources", []) or []
            clu_id = next((s.clu_id for s in sources if getattr(s, "clu_id", None)), None)
            if not entity_id or entity_id in self._exclude or clu_id not in self._uptime_entities:
                continue
            self._light_clu[entity_id] = clu_id
            self._light_uid[entity_id] = light.unique_id or entity_id
        for clu_id, uptime in self._uptime_entities.items():
            if uptime.entity_id:
                self._uptime_clu[uptime.entity_id] = clu_id

        if self._light_clu:
            self._unsubscribe.append(
                async_track_state_change_event(self.hass, list(self._light_clu), self._on_light_change)
            )
            # Record the current states as a baseline
            for entity_id in self._light_clu:
                self._record(entity_id, self.hass.states.get(entity_id))
        if self._uptime_clu:
            self._unsubscribe.append(
                async_track_state_change_event(self.hass, list(self._uptime_clu), self._on_uptime_change)
            )
            for entity_id, clu_id in self._uptime_clu.items():
                self._check_boot(clu_id, self.hass.states.get(entity_id))
        _LOGGER.debug("Restoring %d light(s) after CLU restarts", len(self._light_clu))

    async def async_stop(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        for cancel in self._pending_polls.values():
            cancel()
        self._pending_polls.clear()
        await self._store.async_save(self._data)

    # ------------------------------------------------------------ recording
    def _record(self, entity_id: str, state: Any) -> None:
        snap = _snapshot(state)
        if snap is None:
            return
        uid = self._light_uid[entity_id]
        history: list[dict[str, Any]] = self._data["lights"].setdefault(uid, [])
        if history and _same(history[-1]["state"], snap):
            return
        history.append({"ts": dt_util.utcnow().isoformat(), "state": snap})
        del history[:-HISTORY_PER_LIGHT]
        self._store.async_delay_save(lambda: self._data, SAVE_DELAY)

    @callback
    def _on_light_change(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        self._record(entity_id, new)
        if old is not None and old.state == STATE_UNAVAILABLE and new is not None and new.state != STATE_UNAVAILABLE:
            # Back online: read Uptime now instead of waiting for the slow-read timer
            self._request_uptime(self._light_clu[entity_id])

    def _request_uptime(self, clu_id: str) -> None:
        if clu_id in self._pending_polls:
            return
        poll = getattr(self.coordinator, "_send_slow_poll", None)
        if poll is None:
            return

        async def _poll(_now: Any) -> None:
            self._pending_polls.pop(clu_id, None)
            try:
                await poll(clu_id)
            except Exception as err:  # noqa: BLE001 - best effort, the timer reads it later
                _LOGGER.debug("[%s] Uptime read after reconnect failed: %s", clu_id, err)

        # Short delay lets the CLU finish its post-start registration
        self._pending_polls[clu_id] = async_call_later(self.hass, 2, _poll)

    # ------------------------------------------------------------ restart detection
    @callback
    def _on_uptime_change(self, event: Event[EventStateChangedData]) -> None:
        self._check_boot(self._uptime_clu[event.data["entity_id"]], event.data["new_state"])

    def _check_boot(self, clu_id: str, state: Any) -> None:
        if state is None:
            return
        try:
            uptime = float(state.state)
        except (TypeError, ValueError):
            return
        boot = dt_util.utcnow() - timedelta(seconds=uptime)
        stored = self._data["boot"].get(clu_id)
        previous = dt_util.parse_datetime(stored) if stored else None
        if previous is not None and abs(boot - previous) <= BOOT_TOLERANCE:
            return
        self._data["boot"][clu_id] = boot.isoformat()
        self._store.async_delay_save(lambda: self._data, SAVE_DELAY)
        if previous is not None and boot > previous:
            _LOGGER.warning("[%s] CLU restart detected (booted %s); restoring lights", clu_id, boot.isoformat())
            self.hass.async_create_task(self._async_restore(clu_id, boot))

    async def _async_restore(self, clu_id: str, boot: datetime) -> None:
        for entity_id, light_clu in self._light_clu.items():
            if light_clu != clu_id:
                continue
            history = self._data["lights"].get(self._light_uid[entity_id], [])
            before = [h for h in history if dt_util.parse_datetime(h["ts"]) < boot]
            if not before:
                continue
            target = before[-1]["state"]
            current = _snapshot(self.hass.states.get(entity_id))
            if _same(current, target):
                continue
            try:
                if target["on"]:
                    data: dict[str, Any] = {"entity_id": entity_id}
                    for key in ("brightness", "hs_color", "rgb_color"):
                        if key in target:
                            data[key] = target[key]
                    await self.hass.services.async_call("light", "turn_on", data, blocking=True)
                else:
                    await self.hass.services.async_call("light", "turn_off", {"entity_id": entity_id}, blocking=True)
                _LOGGER.info("[%s] Restored %s to %s", clu_id, entity_id, target)
            except Exception as err:  # noqa: BLE001 - one failing light must not stop the rest
                _LOGGER.warning("[%s] Could not restore %s: %s", clu_id, entity_id, err)
