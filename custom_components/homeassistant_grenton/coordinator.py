from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .clu_settings import subscription_id, validate_subscription_id
from .const import DOMAIN
from .domain.action import GrentonAction
from .domain.api.clu import GrentonCluApi
from .domain.api.clu_health import (
    KEEPALIVE_INTERVAL,
    REALTIME_STALE_AFTER,
    REGISTRATION_INTERVAL,
    CluConnectionHealth,
)
from .domain.api.clu_messages import GrentonCluApiActionRequest
from .domain.clu import GrentonClu
from .domain.device_types import CLU_GATE_HTTP
from .domain.encryption import GrentonEncryption
from .domain.state_object import GrentonStateObject, GrentonVariableValueObject
from .read_policy import slow_read_interval, validate_slow_read_interval
from .state import (
    MISSING_STATE,
    GrentonCluState,
    GrentonCluStateAttributeKey,
    GrentonCluStateVariableKey,
    GrentonRegistrationValue,
    GrentonState,
    GrentonValue,
    MissingState,
)

StateKey = GrentonCluStateVariableKey | GrentonCluStateAttributeKey

_LOGGER = logging.getLogger(__name__)


def _next_periodic_deadline(deadline: float, interval: int, now: float) -> float:
    """Keep the original cadence while skipping ticks missed during work."""
    deadline += interval
    if deadline <= now:
        deadline += (int((now - deadline) // interval) + 1) * interval
    return deadline


class GrentonCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        clus: list[GrentonClu],
        encryption: GrentonEncryption,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
        )

        self.config_entry = config_entry
        self.clus = clus
        self.encryption = encryption
        self.state = GrentonState(clus={clu.id: GrentonCluState() for clu in clus})

        # Map CLU IDs to their API instances
        self._apis: dict[str, GrentonCluApi] = {}
        self._read_locks = {clu.id: asyncio.Lock() for clu in clus}
        self._registration_waiters = dict.fromkeys(self._read_locks, 0)
        self._registrations_idle = {
            clu_id: asyncio.Event() for clu_id in self._read_locks
        }
        for idle in self._registrations_idle.values():
            idle.set()
        self._report_versions: dict[str, dict[StateKey, int]] = {
            clu.id: {} for clu in clus
        }
        self._shutdown_lock = asyncio.Lock()
        self._stopping = False
        self._stop_listener: Callable[[], None] | None = None
        self._realtime_keys: dict[str, set[StateKey]] = {clu.id: set() for clu in clus}
        self._slow_keys: dict[str, set[StateKey]] = {clu.id: set() for clu in clus}
        self._conditional_large_keys: dict[str, set[StateKey]] = {
            clu.id: set() for clu in clus
        }
        self._slow_conditions: dict[
            str, dict[StateKey, list[Callable[[], bool] | None]]
        ] = {clu.id: {} for clu in clus}
        self._slow_success: dict[str, dict[StateKey, tuple[float, datetime]]] = {
            clu.id: {} for clu in clus
        }
        self._slow_read_intervals = {
            clu.id: slow_read_interval(config_entry.options, clu.id) for clu in clus
        }
        self._poll_only_clus = {
            clu.id for clu in clus if clu.device_type == CLU_GATE_HTTP
        }
        self._slow_tasks: dict[str, asyncio.Task] = {}
        self._slow_settings_lock = asyncio.Lock()
        self.connection_health = {clu.id: CluConnectionHealth() for clu in clus}
        self._ping_failures = {clu.id: 0 for clu in clus}
        self._realtime_success: dict[str, dict[StateKey, float]] = {
            clu.id: {} for clu in clus
        }
        self._availability_signatures: dict[str, tuple[bool, frozenset[StateKey]]] = {}
        self._health_signal_prefix = f"grenton_health_{config_entry.entry_id}_"

        # Initialize API instances for each CLU
        for clu in clus:
            self._apis[clu.id] = GrentonCluApi(
                clu,
                encryption,
                health=self.connection_health[clu.id],
                subscription_id=subscription_id(config_entry.options, clu.id),
            )

    def health_update_signal(self, clu_id: str) -> str:
        """Scope local diagnostic updates to this integration entry and CLU."""
        return f"{self._health_signal_prefix}{clu_id}"

    def subscription_count(self, clu_id: str) -> int:
        api = self._apis.get(clu_id)
        return api.subscription_count if api is not None else 0

    def _realtime_key_fresh(self, clu_id: str, key: StateKey) -> bool:
        stamp = self._realtime_success[clu_id].get(
            key, self.connection_health[clu_id].started_at
        )
        return monotonic() - stamp < REALTIME_STALE_AFTER

    def states_available(self, states: list[GrentonStateObject]) -> bool:
        """Expire realtime sources; polled entities retain their existing policy."""
        return all(
            self.state_read_mode(state) != "realtime" or self.is_state_fresh(state)
            for state in states
        )

    def _publish_clu_update(self, clu_id: str, *, values_changed: bool = False) -> None:
        """Refresh diagnostics locally; wake all entities only for state/availability changes."""
        if self._stopping:
            return
        signature = (
            self.connection_health[clu_id].connected is not False,
            frozenset(
                key
                for key in self._realtime_keys[clu_id]
                if not self._realtime_key_fresh(clu_id, key)
            ),
        )
        changed = self._availability_signatures.get(clu_id) != signature
        self._availability_signatures[clu_id] = signature
        async_dispatcher_send(self.hass, self.health_update_signal(clu_id))
        if values_changed or changed:
            self.async_set_updated_data(self.state.__dict__)

    async def _async_update_data(self):  # type: ignore
        return self.state

    async def _send_ping(self, clu_id: str) -> None:
        if self._stopping:
            return
        api = self._apis.get(clu_id)
        if not api:
            _LOGGER.warning("[%s] No API found for CLU during ping", clu_id)
            return

        try:
            success = await api.ping()
            if not success:
                self._ping_failures[clu_id] += 1
                _LOGGER.warning(
                    "[%s] Ping failed (consecutive=%d): %s; %s",
                    api.log_identity,
                    self._ping_failures[clu_id],
                    api.last_ping_summary,
                    api.diagnostic_context(),
                )
            elif failures := self._ping_failures[clu_id]:
                self._ping_failures[clu_id] = 0
                _LOGGER.info(
                    "[%s] Ping recovered after %d failed cycle(s): %s; %s",
                    api.log_identity,
                    failures,
                    api.last_ping_summary,
                    api.diagnostic_context(),
                )
        except Exception as e:  # noqa: BLE001 - isolate each CLU's keepalive failures
            self._ping_failures[clu_id] += 1
            _LOGGER.error(
                "[%s] Error during ping (consecutive=%d): %s: %s; %s",
                api.log_identity,
                self._ping_failures[clu_id],
                type(e).__name__,
                e,
                api.diagnostic_context(),
            )
        finally:
            self._publish_clu_update(clu_id)

    async def _periodic_clu_loop(
        self, clu_id: str, interval: int, *, register: bool
    ) -> None:
        """A slow/offline CLU must not delay another CLU's keepalives/refreshes."""
        deadline = monotonic() + interval
        while not self._stopping:
            await asyncio.sleep(max(0, deadline - monotonic()))
            if self._stopping:
                return
            try:
                if register:
                    if self._realtime_keys[clu_id]:
                        await self._send_register(clu_id)
                else:
                    await self._send_ping(clu_id)
            except Exception as error:  # noqa: BLE001 - keep this CLU's timer alive after failures
                _LOGGER.error(
                    "[%s] Periodic %s failed: %s",
                    clu_id,
                    "registration" if register else "keepalive",
                    error,
                )
            deadline = _next_periodic_deadline(deadline, interval, monotonic())

    async def _ping_loop(self) -> None:
        await asyncio.gather(
            *(
                self._periodic_clu_loop(clu_id, KEEPALIVE_INTERVAL, register=False)
                for clu_id in self._apis
            )
        )

    @staticmethod
    def _state_key(
        state: GrentonStateObject,
    ) -> GrentonCluStateVariableKey | GrentonCluStateAttributeKey:
        if isinstance(state, GrentonVariableValueObject):
            return GrentonCluStateVariableKey(state.index)
        return GrentonCluStateAttributeKey(state.object_name, state.index)

    async def _send_register(
        self, clu_id: str, required_keys: set[StateKey] | None = None
    ) -> set[StateKey]:
        async with self._registration_read_lock(clu_id):
            if self._stopping:
                return set()
            return await self._read_registered_states(clu_id, required_keys)

    @asynccontextmanager
    async def _registration_read_lock(self, clu_id: str) -> AsyncIterator[None]:
        """Let queued renewals run before the next slow-read batch."""
        self._registration_waiters[clu_id] += 1
        self._registrations_idle[clu_id].clear()
        try:
            async with self._read_locks[clu_id]:
                yield
        finally:
            self._registration_waiters[clu_id] -= 1
            if not self._registration_waiters[clu_id]:
                self._registrations_idle[clu_id].set()

    async def _read_registered_states(
        self, clu_id: str, required_keys: set[StateKey] | None = None
    ) -> set[StateKey]:
        api = self._apis.get(clu_id)
        if not api:
            _LOGGER.warning(
                "[%s] No API found for CLU during state registration", clu_id
            )
            return set()

        clu_state = self.state.clus[clu_id]

        # Check if there are any states to register
        if not self._realtime_keys[clu_id] or (
            required_keys is not None
            and required_keys.isdisjoint(self._realtime_keys[clu_id])
        ):
            _LOGGER.debug("[%s] No component states to register", clu_id)
            return set()

        try:
            keys = [
                key
                for key in clu_state.get_subscription_order()
                if key in self._realtime_keys[clu_id]
            ]
            versions = self._report_versions[clu_id].copy()
            started_at = monotonic()
            values = (
                await api.register_component_states(keys)
                if required_keys is None
                else await api.register_component_states(
                    keys, required_keys=required_keys
                )
            )
            if self._stopping:
                return set()
            if values is None or len(values) != len(keys):
                _LOGGER.warning("[%s] Incomplete state registration response", clu_id)
                return set()
            # A pushed change received during the read is newer than its snapshot.
            current = self._report_versions[clu_id]
            merged: list[GrentonRegistrationValue] = [
                value if current.get(key, 0) == versions.get(key, 0) else MISSING_STATE
                for key, value in zip(keys, values)
            ]
            clu_state.update_keys(keys, merged)
            for key, value in zip(keys, merged):
                if not isinstance(value, MissingState):
                    self._realtime_success[clu_id][key] = started_at
            self._publish_clu_update(clu_id, values_changed=True)
            return {
                key
                for key, value in zip(keys, values)
                if not isinstance(value, MissingState)
                or current.get(key, 0) != versions.get(key, 0)
            }
        except Exception as e:  # noqa: BLE001 - keep later CLU registrations running
            _LOGGER.error("[%s] Error during registration: %s", clu_id, e)
            return set()

    async def _register_loop(self) -> None:
        await asyncio.gather(
            *(
                self._periodic_clu_loop(clu_id, REGISTRATION_INTERVAL, register=True)
                for clu_id in self._apis
                if self._realtime_keys[clu_id]
            )
        )

    async def execute_action(
        self, action: GrentonAction, *, raise_on_error: bool = False
    ) -> None:
        if self._stopping:
            if raise_on_error:
                raise HomeAssistantError("Grenton is shutting down")
            return
        api = self._apis.get(action.clu_id)
        if not api:
            if raise_on_error:
                raise HomeAssistantError(f"CLU {action.clu_id} is not loaded")
            _LOGGER.warning(
                "[%s] No API found for CLU during action execution", action.clu_id
            )
            return

        try:
            success = await api.execute_action(action)
            if not success:
                if raise_on_error:
                    raise HomeAssistantError(f"CLU {action.clu_id} rejected the action")
                _LOGGER.warning(
                    "[%s] Action execution failed for payload: %s",
                    action.clu_id,
                    GrentonCluApiActionRequest.from_action(action).payload,
                )
        except Exception as e:
            if raise_on_error:
                raise HomeAssistantError(
                    f"Could not execute action on CLU {action.clu_id}: {e}"
                ) from e
            _LOGGER.error("[%s] Error executing action: %s", action.clu_id, e)
        finally:
            self._publish_clu_update(action.clu_id)

    async def _process_report(
        self,
        clu_id: str,
        keys: list[GrentonCluStateVariableKey | GrentonCluStateAttributeKey],
        values: list[GrentonValue],
    ) -> None:
        """Process a report from a CLU and update state for the given keys."""
        if self._stopping:
            return
        if len(keys) != len(values):
            _LOGGER.warning("[%s] Ignoring incomplete state report", clu_id)
            return
        clu_state = self.state.clus[clu_id]
        for key in keys:
            versions = self._report_versions[clu_id]
            versions[key] = versions.get(key, 0) + 1
        clu_state.update_keys(keys, values)
        for key in keys:
            if key in self._realtime_keys[clu_id]:
                self._realtime_success[clu_id][key] = monotonic()
        self._publish_clu_update(clu_id, values_changed=True)
        _LOGGER.debug("[%s] Processed report with %d values", clu_id, len(values))

    def register_component_state(
        self,
        state: GrentonStateObject,
        *,
        large_value: bool = False,
        read_mode: str = "realtime",
        poll_condition: Callable[[], bool] | None = None,
    ) -> None:
        self.state.register_state(state)
        key = self._state_key(state)
        if state.clu_id not in self._realtime_keys:
            return
        conditional_large = (
            large_value and read_mode == "slow" and poll_condition is not None
        )
        if conditional_large:
            # The owning thermostat controls this expensive read. Other
            # consumers cannot turn it into an unconditional subscription
            # or poll, even if they registered the same binding first.
            if key not in self._conditional_large_keys[state.clu_id]:
                self._slow_conditions[state.clu_id].pop(key, None)
            self._conditional_large_keys[state.clu_id].add(key)
            self._realtime_keys[state.clu_id].discard(key)
            self._slow_keys[state.clu_id].add(key)
        elif key not in self._conditional_large_keys[state.clu_id]:
            if state.clu_id in self._poll_only_clus or (
                read_mode == "slow" and key not in self._realtime_keys[state.clu_id]
            ):
                self._slow_keys[state.clu_id].add(key)
            elif read_mode != "slow":
                self._realtime_keys[state.clu_id].add(key)
                self._slow_keys[state.clu_id].discard(key)
        if key in self._slow_keys[state.clu_id] and (
            conditional_large or key not in self._conditional_large_keys[state.clu_id]
        ):
            self._slow_conditions[state.clu_id].setdefault(key, []).append(
                poll_condition
            )
        if large_value and (api := self._apis.get(state.clu_id)) is not None:
            api.large_value_keys.add(self._state_key(state))

    async def async_refresh_clu_state(
        self, clu_id: str, *, required_states: list[GrentonStateObject] | None = None
    ) -> bool:
        """Read back tracked values; report whether the required reads succeeded."""
        if required_states is None:
            received = await self._send_register(clu_id)
            received |= await self._send_slow_poll(clu_id)
            required = self._realtime_keys[clu_id] | {
                key
                for key in self._slow_keys[clu_id]
                if self._slow_poll_enabled(clu_id, key)
            }
            return required <= received
        required = {self._state_key(state) for state in required_states}
        received = await self._send_register(clu_id, required)
        if slow_required := required & self._slow_keys[clu_id]:
            received |= await self._send_slow_poll(clu_id, slow_required)
        return required <= received

    def state_read_mode(self, state: GrentonStateObject) -> str:
        return (
            "slow"
            if self._state_key(state) in self._slow_keys.get(state.clu_id, set())
            else "realtime"
        )

    def last_polled(self, state: GrentonStateObject) -> str | None:
        stamp = self._slow_success.get(state.clu_id, {}).get(self._state_key(state))
        return (
            stamp[1].isoformat()
            if stamp is not None and self.state_read_mode(state) == "slow"
            else None
        )

    def is_state_fresh(self, state: GrentonStateObject) -> bool:
        if state.clu_id not in self.connection_health:
            return False
        if self.state_read_mode(state) != "slow":
            return self.connection_health[
                state.clu_id
            ].connected is not False and self._realtime_key_fresh(
                state.clu_id, self._state_key(state)
            )
        stamp = self._slow_success[state.clu_id].get(self._state_key(state))
        # Keep the last confirmed schedule visible while periodic reads are paused.
        if not self._slow_poll_enabled(state.clu_id, self._state_key(state)):
            return stamp is not None
        return (
            stamp is not None
            and monotonic() - stamp[0] < self._slow_read_intervals[state.clu_id] * 2
        )

    def _slow_poll_enabled(self, clu_id: str, key: StateKey) -> bool:
        conditions = self._slow_conditions[clu_id].get(key, [])
        return not conditions or any(
            condition is None or condition() for condition in conditions
        )

    def _conditional_slow_key(self, clu_id: str, key: StateKey) -> bool:
        conditions = self._slow_conditions[clu_id].get(key, [])
        return bool(conditions) and all(
            condition is not None for condition in conditions
        )

    async def _send_slow_poll(
        self,
        clu_id: str,
        required_keys: set[StateKey] | None = None,
        *,
        conditional_only: bool | None = None,
    ) -> set[StateKey]:
        if self._stopping or (api := self._apis.get(clu_id)) is None:
            return set()
        received: set[StateKey] = set()
        # Ordinary mode/power reads must be merged before conditional schedule
        # reads, including when HTTP Gate is the source of those conditions.
        phases = (False, True) if conditional_only is None else (conditional_only,)
        for conditional in phases:
            candidates = [
                key
                for key in self.state.clus[clu_id].get_subscription_order()
                if key in self._slow_keys[clu_id]
                and self._conditional_slow_key(clu_id, key) == conditional
                and (required_keys is None or key in required_keys)
            ]
            for batch in api.state_read_batches(candidates):
                await self._registrations_idle[clu_id].wait()
                async with self._read_locks[clu_id]:
                    if self._stopping or self._apis.get(clu_id) is not api:
                        return set()
                    # A queued renewal or an earlier batch may have changed the
                    # thermostat mode. Test eligibility immediately before send.
                    keys = [
                        key
                        for key in batch
                        if key in self._slow_keys[clu_id]
                        and (
                            required_keys is not None
                            or self._slow_poll_enabled(clu_id, key)
                        )
                    ]
                    if not keys:
                        continue
                    try:
                        stamp = (monotonic(), datetime.now(UTC))
                        values = await api.poll_component_states(keys)
                        if self._stopping:
                            return set()
                        if len(values) != len(keys):
                            _LOGGER.warning(
                                "[%s] Incomplete slow-read response", clu_id
                            )
                        else:
                            self.state.clus[clu_id].update_keys(keys, values)
                            for key, value in zip(keys, values):
                                if not isinstance(value, MissingState):
                                    self._slow_success[clu_id][key] = stamp
                                    received.add(key)
                    except Exception as error:  # noqa: BLE001 - keep polling after unexpected read errors
                        _LOGGER.warning("[%s] Slow read failed: %s", clu_id, error)
                # Publish each batch, including failures that may expire stale
                # values, before yielding to a renewal or another CLU's work.
                self._publish_clu_update(clu_id, values_changed=True)
                await asyncio.sleep(0)
        return received

    async def _slow_poll_loop(self, clu_id: str) -> None:
        interval = self._slow_read_intervals[clu_id]
        deadline = monotonic() + interval
        while not self._stopping:
            await asyncio.sleep(max(0, deadline - monotonic()))
            if self._stopping:
                return
            try:
                await self._send_slow_poll(clu_id)
            except Exception as error:  # noqa: BLE001 - retry only on the configured polling cadence
                _LOGGER.error("[%s] Polling failed: %s", clu_id, error)
            deadline = _next_periodic_deadline(deadline, interval, monotonic())

    def _start_slow_task(self, clu_id: str) -> None:
        if not self._stopping and self._slow_keys[clu_id]:
            self._slow_tasks[clu_id] = asyncio.create_task(self._slow_poll_loop(clu_id))
            _LOGGER.info(
                "[%s] Polling %d values every %d seconds on the control socket",
                clu_id,
                len(self._slow_keys[clu_id]),
                self._slow_read_intervals[clu_id],
            )

    def _start_slow_tasks(self) -> None:
        for clu_id in self._slow_keys:
            self._start_slow_task(clu_id)

    async def async_set_slow_read_interval(self, clu_id: str, interval: int) -> None:
        async with self._slow_settings_lock:
            if clu_id not in self._slow_read_intervals:
                raise ValueError("Unknown CLU")
            self._slow_read_intervals[clu_id] = validate_slow_read_interval(interval)
            if task := self._slow_tasks.pop(clu_id, None):
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self._start_slow_task(clu_id)
            self.async_set_updated_data(self.state.__dict__)

    async def async_set_subscription_id(self, clu_id: str, value: int) -> None:
        """Reconcile only this CLU's groups on their existing sockets."""
        value = validate_subscription_id(value)
        if clu_id not in self._apis:
            raise HomeAssistantError("Unknown CLU")
        api = self._apis[clu_id]
        if api.subscription_id == value:
            return
        async with self._registration_read_lock(clu_id):
            if self._stopping:
                raise HomeAssistantError("Grenton is stopping")
            if api.subscription_id == value:
                return
            await api.async_set_subscription_id(value)
            # Snapshot merging and report versions follow the normal read path.
            # An offline CLU retains the desired ID and retries on its cadence.
            await self._read_registered_states(clu_id)

    async def async_setup(self) -> None:
        self._stop_listener = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._async_handle_stop
        )
        # Connect all APIs
        connection_tasks: list[Any] = []
        for clu in self.clus:
            api = self._apis[clu.id]
            connection_tasks.append(self._connect_api(api))

        # Wait for all connections to complete
        await asyncio.gather(*connection_tasks, return_exceptions=True)

        # Check connectivity before the initial state reads.
        ping_tasks = [self._send_ping(clu_id) for clu_id in self._apis]
        if ping_tasks:
            await asyncio.gather(*ping_tasks, return_exceptions=True)

        # Keepalive and renewal clocks start before startup reads: a slow CLU
        # or many slow-read batches must not postpone the first renewal.
        self._ping_task = asyncio.create_task(self._ping_loop())
        self._register_task = asyncio.create_task(self._register_loop())

        # Send initial registrations
        register_tasks = [self._send_register(clu_id) for clu_id in self.state.clus]
        if register_tasks:
            results = await asyncio.gather(*register_tasks, return_exceptions=True)
            # Retry incomplete initial pulls once before publishing entities.
            retries = [
                self._send_register(
                    clu_id,
                    self._realtime_keys[clu_id]
                    - (result if isinstance(result, set) else set()),
                )
                for clu_id, result in zip(self.state.clus, results)
                if not isinstance(result, set)
                or not self._realtime_keys[clu_id] <= result
            ]
            if retries:
                await asyncio.gather(*retries, return_exceptions=True)

        # Read all ordinary sources before evaluating schedule conditions, even
        # when a thermostat's mode/power bindings live on another (polled) CLU.
        for conditional_only in (False, True):
            await asyncio.gather(
                *(
                    self._send_slow_poll(clu_id, conditional_only=conditional_only)
                    for clu_id, keys in self._slow_keys.items()
                    if keys
                )
            )

        # Start background tasks
        if self._stopping:
            raise HomeAssistantError("Grenton setup was interrupted by shutdown")
        self._start_slow_tasks()

    async def _connect_api(self, api: GrentonCluApi) -> None:
        """Connect a single API instance."""
        try:
            success = await api.connect()
            if not success:
                _LOGGER.error("Failed to connect API for CLU %s", api.clu.id)
                return

            # The shared report listener maps subscription IDs to their keys
            # before delivering values through this hook.
            async def handle_subscription(
                keys: list[GrentonCluStateVariableKey | GrentonCluStateAttributeKey],
                values: list[GrentonValue],
            ) -> None:
                await self._process_report(api.clu.id, keys, values)

            api.on_subscription_report = handle_subscription
        except Exception as e:  # noqa: BLE001 - isolate setup failures to this CLU
            _LOGGER.error("Error connecting API for CLU %s: %s", api.clu.id, e)

    async def _async_handle_stop(self, event: Event) -> None:
        # async_listen_once already removed this listener before dispatch.
        self._stop_listener = None
        await self.async_shutdown()

    async def async_shutdown(self) -> None:
        """Stop work, remove owned subscriptions, and close local UDP sockets."""
        async with self._shutdown_lock:
            self._stopping = True
            if self._stop_listener is not None:
                self._stop_listener()
                self._stop_listener = None
            tasks = [
                task
                for name in ("_ping_task", "_register_task")
                if (task := getattr(self, name, None)) is not None
            ]
            tasks.extend(self._slow_tasks.values())
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._slow_tasks.clear()
            # The API attempts bounded remote removal before local UDP close.
            await asyncio.gather(
                *(self._disconnect_api(api) for api in self._apis.values()),
                return_exceptions=True,
            )
            self._apis.clear()

    async def _disconnect_api(self, api: GrentonCluApi) -> None:
        """Disconnect a single API instance."""
        try:
            await api.disconnect()
        except Exception as e:  # noqa: BLE001 - still close the other CLU APIs
            _LOGGER.error("Error disconnecting API for CLU %s: %s", api.clu.id, e)

    def get_value_for_component(self, state: GrentonStateObject) -> GrentonValue | None:
        """Get the value for a component from the state."""
        if not self.is_state_fresh(state):
            return None
        return self.state.get_value_for_component(state)
