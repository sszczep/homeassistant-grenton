from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import cast

from ...clu_settings import DEFAULT_SUBSCRIPTION_ID, validate_subscription_id
from ...state import (
    MISSING_STATE,
    GrentonCluStateAttributeKey,
    GrentonCluStateVariableKey,
    GrentonRegistrationValue,
    GrentonValue,
)
from ..action import GrentonAction
from ..cipher import GrentonCipher
from ..clu import GrentonClu
from ..encryption import GrentonEncryption
from .clu_health import CluConnectionHealth
from .clu_messages import (
    GrentonCluApiActionRequest,
    GrentonCluApiClientDestroyRequest,
    GrentonCluApiClientDestroyResponse,
    GrentonCluApiClientRegisterRequest,
    GrentonCluApiClientRegisterResponse,
    GrentonCluApiClientReportNotification,
    GrentonCluApiFetchValuesRequest,
    GrentonCluApiFetchValuesResponse,
    GrentonCluApiGetValueRequest,
    GrentonCluApiGetValueResponse,
    GrentonCluApiMessageParser,
    GrentonCluApiPingRequest,
    GrentonCluApiRequest,
)

_LOGGER = logging.getLogger(__name__)

# A conservative key budget, not a firmware limit on UDP datagram size.
MAX_KEYS_PER_REGISTER = 30
MIN_SEND_INTERVAL = 0.02
SUBSCRIPTION_CLEANUP_TIMEOUT = 2.0
MAX_SUBSCRIPTION_ID = 65535
REPORT_BIND_ATTEMPTS = 8

StateKey = GrentonCluStateVariableKey | GrentonCluStateAttributeKey


def _diagnostic_targets(keys: Sequence[StateKey]) -> list[str]:
    """Identify a batch without logging its state values or a long key list."""
    targets = [
        f"{key.object_name}.{key.name}"
        if isinstance(key, GrentonCluStateAttributeKey)
        else f"var:{key.name}"
        for key in keys[:3]
    ]
    if len(keys) > 3:
        targets.append(f"+{len(keys) - 3} more")
    return targets


class _RequestGate:
    """Ordinary requests may overlap; a large read runs on its own.

    Holding the FIFO turnstile while waiting for active requests to finish
    prevents later pings or writes from overtaking a queued large read.
    """

    def __init__(self) -> None:
        self._turnstile = asyncio.Lock()
        self._active = 0
        self._idle = asyncio.Event()
        self._idle.set()

    @asynccontextmanager
    async def access(self, *, exclusive: bool) -> AsyncIterator[None]:
        if exclusive:
            async with self._turnstile:
                await self._idle.wait()
                yield
            return
        async with self._turnstile:
            self._active += 1
            self._idle.clear()
        try:
            yield
        finally:
            # No await between decrementing and waking the exclusive waiter:
            # cancellation cannot leave the gate permanently occupied.
            self._active -= 1
            if not self._active:
                self._idle.set()


@dataclass
class _SubscriptionGroup:
    """Keys belonging to one identity on the shared report listener.

    registered tracks a request that may have reached the CLU, even if its reply
    was lost. confirmed records a validated registration reply.
    """

    keys: list[StateKey]
    subscription_id: int
    registered: bool = False
    confirmed: bool = False
    report_address: tuple[str, int] | None = None


class GrentonCluApi:
    """One control socket and one shared notification listener per CLU."""

    def __init__(
        self,
        clu: GrentonClu,
        encryption: GrentonEncryption,
        *,
        health: CluConnectionHealth | None = None,
        subscription_id: int = DEFAULT_SUBSCRIPTION_ID,
    ):
        self.clu = clu
        self.encryption = encryption
        self.cipher = GrentonCipher(encryption)
        self.health = health if health is not None else CluConnectionHealth()
        self._subscription_id = validate_subscription_id(subscription_id)
        self._group_base_id = self._subscription_id
        self._next_subscription_id = self._subscription_id
        self._used_subscription_ids: set[int] = set()
        self._report_address_history: set[tuple[str, int]] = set()
        self._rebase_requested = False
        self._action_lock = asyncio.Lock()
        self._request_gate = _RequestGate()
        self._send_lock = asyncio.Lock()
        self._next_send_at = 0.0
        self._connect_lock = asyncio.Lock()
        self._disconnect_lock = asyncio.Lock()
        self._registration_lock = asyncio.Lock()
        self._registration_waiters = 0
        self._registrations_idle = asyncio.Event()
        self._registrations_idle.set()
        self._generation = 0
        self._opening_protocols: set[GrentonCluApiProtocol] = set()
        self.large_value_keys: set[StateKey] = set()
        self._closed = False
        self._closing = False
        self._closing_callbacks: set[asyncio.Task] = set()

        self.transport: asyncio.DatagramTransport | None = None
        self.protocol: GrentonCluApiProtocol | None = None
        self.report_transport: asyncio.DatagramTransport | None = None
        self.report_protocol: GrentonCluApiProtocol | None = None
        self._report_address: tuple[str, int] | None = None
        self._groups: list[_SubscriptionGroup] = []
        self._groups_by_id: dict[int, _SubscriptionGroup] = {}
        self._retired_groups: dict[int, _SubscriptionGroup] = {}
        self.last_ping_summary = "no completed ping cycle"
        self.on_subscription_report: (
            Callable[[list[StateKey], list[GrentonValue]], Awaitable[None]] | None
        ) = None

    @property
    def subscription_id(self) -> int:
        """First identity to allocate when this CLU's groups are created."""
        return self._subscription_id

    async def async_set_subscription_id(self, value: int) -> None:
        value = validate_subscription_id(value)
        async with self._registration_lock:
            if self._subscription_id != value:
                self._subscription_id = value
                self._rebase_requested = True

    @property
    def subscription_count(self) -> int:
        """Count confirmed groups on the current report listener."""
        if self.report_protocol is None or not self.report_protocol.active:
            return 0
        return sum(group.confirmed for group in self._groups)

    @property
    def log_identity(self) -> str:
        return f"{self.clu.name}/{self.clu.id}"

    def diagnostic_context(self) -> str:
        return (
            f"remote={self.clu.ip}:{self.clu.port}; "
            f"subscriptions={self.subscription_count}/{len(self._groups)} ready; "
            f"pending_removals={len(self._retired_groups)}; "
            f"last_clu_response={self.health.describe_last_response()}; "
            f"total_timeouts={self.health.request_timeouts}; "
            f"read_busy={self._registration_lock.locked()}; "
            f"action_busy={self._action_lock.locked()}"
        )

    def _current(self, generation: int) -> bool:
        return not self._closed and not self._closing and generation == self._generation

    async def connect(self) -> bool:
        """Connect UDP locally so its selected route supplies our report IP."""
        generation = self._generation
        async with self._connect_lock:
            if self._closing or generation != self._generation:
                return False
            if (
                self.transport is not None
                and self.protocol is not None
                and self.protocol.active
            ):
                return True
            await self._close_socket(self.transport, self.protocol)
            if self._closing or generation != self._generation:
                return False
            self.transport = None
            self._closed = False
            protocol = GrentonCluApiProtocol(self)
            self.protocol = protocol
            self._opening_protocols.add(protocol)
            try:
                (
                    transport,
                    _,
                ) = await asyncio.get_running_loop().create_datagram_endpoint(
                    lambda: protocol,
                    local_addr=("0.0.0.0", 0),
                    remote_addr=(self.clu.ip, self.clu.port),
                )
                if protocol.transport is None and not protocol.closed:
                    protocol.connection_made(transport)
                if not self._current(generation) or protocol.closed:
                    await self._close_socket(transport, protocol)
                    if self.protocol is protocol:
                        self.protocol = None
                    return False
                self.transport = transport
                _LOGGER.debug("[%s] Opened control UDP socket", self.log_identity)
                return True
            except BaseException as error:
                await self._close_socket(protocol.transport, protocol)
                if self.protocol is protocol:
                    self.protocol = None
                if not isinstance(error, Exception):
                    raise
                _LOGGER.error(
                    "[%s] Failed to open control UDP socket: %s",
                    self.log_identity,
                    error,
                )
                return False
            finally:
                self._opening_protocols.discard(protocol)

    @staticmethod
    def _stop_socket(transport, protocol) -> GrentonCluApiProtocol | None:
        owned = None
        if isinstance(protocol, GrentonCluApiProtocol):
            owned = protocol.transport
            protocol.close()
        if (
            transport is not None
            and transport is not owned
            and not transport.is_closing()
        ):
            transport.close()
        return protocol if isinstance(protocol, GrentonCluApiProtocol) else None

    @staticmethod
    async def _close_socket(transport, protocol) -> None:
        if owned := GrentonCluApi._stop_socket(transport, protocol):
            await owned.wait_closed()

    async def _close_sockets(self, sockets) -> None:
        protocols = set()
        # Close every local port synchronously before awaiting callback cleanup.
        for transport, protocol in sockets:
            try:
                if owned := self._stop_socket(transport, protocol):
                    protocols.add(owned)
            except Exception as error:  # noqa: BLE001 - still close the other ports
                _LOGGER.error(
                    "[%s] Error closing UDP socket: %s", self.log_identity, error
                )
        for protocol in protocols:
            await protocol.wait_closed()

    def _retire_groups(self) -> None:
        for group in self._groups:
            group.confirmed = False
            if group.registered:
                self._retired_groups[group.subscription_id] = group
        self._groups = []
        self._groups_by_id.clear()

    async def _cleanup_retired_groups(self) -> bool:
        """Bound the entire cleanup attempt, not each individual request."""
        if not self._retired_groups:
            return True
        protocol = self.protocol
        if protocol is None or not protocol.active:
            return False
        try:
            async with asyncio.timeout(SUBSCRIPTION_CLEANUP_TIMEOUT):
                for group in list(self._retired_groups.values()):
                    if group.report_address is None:
                        continue
                    report_ip, report_port = group.report_address
                    try:
                        wire = await protocol.send_request(
                            GrentonCluApiClientDestroyRequest(
                                group.subscription_id,
                                report_ip=report_ip,
                                report_port=report_port,
                            )
                        )
                        if wire is None:
                            continue
                        GrentonCluApiClientDestroyResponse(wire, group.subscription_id)
                    except (ConnectionError, ValueError):
                        continue
                    if self._retired_groups.get(group.subscription_id) is group:
                        self._retired_groups.pop(group.subscription_id)
        except TimeoutError:
            pass
        if self._retired_groups:
            _LOGGER.warning(
                "[%s] Removal of %d owned subscription(s) is unconfirmed",
                self.log_identity,
                len(self._retired_groups),
            )
        return not self._retired_groups

    async def _close_report_listener(self) -> None:
        transport, protocol = self.report_transport, self.report_protocol
        self.report_transport = self.report_protocol = None
        self._report_address = None
        await self._close_socket(transport, protocol)

    async def disconnect(self) -> None:
        """Best-effort remote cleanup, then always close our local UDP ports."""
        # A callback cancelled by an existing disconnect must not wait for it.
        if self._closing and asyncio.current_task() in self._closing_callbacks:
            return
        async with self._disconnect_lock:
            if (
                self._closed
                and self.transport is None
                and self.report_transport is None
            ):
                return
            self._closing = True
            self._closing_callbacks = {
                task
                for protocol in (self.protocol, self.report_protocol)
                if protocol is not None
                for task in getattr(protocol, "_report_tasks", ())
            }
            self.on_subscription_report = None
            self._retire_groups()
            try:
                await self._cleanup_retired_groups()
            finally:
                self._closed = True
                self._generation += 1
                sockets = [
                    (self.transport, self.protocol),
                    (self.report_transport, self.report_protocol),
                    *((item.transport, item) for item in self._opening_protocols),
                ]
                self.transport = self.protocol = None
                self.report_transport = self.report_protocol = None
                self._report_address = None
                self._groups = []
                self._groups_by_id.clear()
                self._retired_groups.clear()
                try:
                    await self._close_sockets(sockets)
                finally:
                    self._closing = False
                    self._closing_callbacks.clear()

    async def ping(self) -> bool:
        """Check only the control socket; subscriptions renew independently."""
        if self._closed or self._closing:
            self.last_ping_summary = "not attempted: API is closed"
            return False
        if (
            self.protocol is None or not self.protocol.active
        ) and not await self.connect():
            self.last_ping_summary = "not attempted: control socket could not be opened"
            return False
        protocol = self.protocol
        if protocol is None:
            self.last_ping_summary = "not attempted: control socket was closed"
            return False
        try:
            wire = await protocol.send_request(GrentonCluApiPingRequest())
        except ConnectionError:
            wire = None
        succeeded = wire is not None
        self.last_ping_summary = f"{int(succeeded)}/1 endpoints replied"
        if not succeeded:
            self.last_ping_summary += "; failed=control: no reply"
        return succeeded

    async def _ensure_report_listener(self) -> bool:
        """Bind a shared listener to the control socket's routed local IP."""
        if self._closed or self._closing:
            return False
        if self.report_protocol is not None and self.report_protocol.active:
            return True
        generation = self._generation
        self._retire_groups()
        if not await self._cleanup_retired_groups() or not self._current(generation):
            return False
        await self._close_report_listener()
        if not self._current(generation):
            return False
        if (
            self.protocol is None or not self.protocol.active
        ) and not await self.connect():
            return False
        address = self.transport.get_extra_info("sockname") if self.transport else None
        if (
            not isinstance(address, tuple)
            or len(address) < 2
            or address[0] == "0.0.0.0"
        ):
            _LOGGER.error(
                "[%s] Cannot determine a routable report address", self.log_identity
            )
            return False
        return await self._bind_report_listener(address[0], generation)

    async def _bind_report_listener(self, local_ip: str, generation: int) -> bool:
        """Never reuse an old wire destination in this API instance.

        A new listener may reuse subscription IDs, so its OS-assigned port must
        also be new. Otherwise delayed reports could match unrelated new keys.
        """
        for _ in range(REPORT_BIND_ATTEMPTS):
            protocol = GrentonCluApiProtocol(self, report_listener=True)

            def make_protocol(
                candidate: GrentonCluApiProtocol = protocol,
            ) -> GrentonCluApiProtocol:
                return candidate

            self._opening_protocols.add(protocol)
            try:
                (
                    transport,
                    _,
                ) = await asyncio.get_running_loop().create_datagram_endpoint(
                    make_protocol, local_addr=(local_ip, 0)
                )
                if protocol.transport is None and not protocol.closed:
                    protocol.connection_made(transport)
                if not self._current(generation) or protocol.closed:
                    await self._close_socket(transport, protocol)
                    return False
                bound = transport.get_extra_info("sockname")
                if not isinstance(bound, tuple) or len(bound) < 2 or not bound[1]:
                    raise ValueError("Report listener has no bound UDP port")
                report_address = (bound[0], bound[1])
                if report_address in self._report_address_history:
                    await self._close_socket(transport, protocol)
                    continue
                self._report_address_history.add(report_address)
                self.report_transport, self.report_protocol = transport, protocol
                self._report_address = report_address
                self._used_subscription_ids = set(self._retired_groups)
                self._next_subscription_id = self.subscription_id
                _LOGGER.debug(
                    "[%s] Opened shared UDP report listener", self.log_identity
                )
                return True
            except BaseException as error:
                await self._close_socket(protocol.transport, protocol)
                if not isinstance(error, Exception):
                    raise
                _LOGGER.error(
                    "[%s] Failed to open report listener: %s", self.log_identity, error
                )
                return False
            finally:
                self._opening_protocols.discard(protocol)
        _LOGGER.error(
            "[%s] Could not obtain an unused report listener port after %d attempts",
            self.log_identity,
            REPORT_BIND_ATTEMPTS,
        )
        return False

    def _allocate_subscription_id(self) -> int:
        for _ in range(MAX_SUBSCRIPTION_ID):
            candidate = self._next_subscription_id
            self._next_subscription_id = candidate % MAX_SUBSCRIPTION_ID + 1
            if candidate not in self._used_subscription_ids:
                self._used_subscription_ids.add(candidate)
                return candidate
        raise RuntimeError("No unused subscription IDs remain on this listener")

    def state_read_batches(self, keys: list[StateKey]) -> list[list[StateKey]]:
        """Deduplicate ordinary reads in groups of 30 and isolate large values."""
        unique = list(dict.fromkeys(keys))
        ordinary = [key for key in unique if key not in self.large_value_keys]
        return [
            ordinary[offset : offset + MAX_KEYS_PER_REGISTER]
            for offset in range(0, len(ordinary), MAX_KEYS_PER_REGISTER)
        ] + [[key] for key in unique if key in self.large_value_keys]

    async def register_component_states(
        self, keys: list[StateKey], *, required_keys: set[StateKey] | None = None
    ) -> Sequence[GrentonRegistrationValue] | None:
        """Renew groups using fresh request IDs, with priority over slow batches."""
        generation = self._generation
        self._registration_waiters += 1
        self._registrations_idle.clear()
        try:
            async with self._registration_lock:
                if not self._current(generation):
                    return None
                if not keys:
                    self._retire_groups()
                    await self._cleanup_retired_groups()
                    return []
                if not await self._ensure_report_listener() or not self._current(
                    generation
                ):
                    return [MISSING_STATE] * len(keys)

                subscribed = {key for group in self._groups for key in group.keys}
                rebase = (
                    self._rebase_requested
                    or self._group_base_id != self.subscription_id
                )
                rebuild = (
                    rebase
                    or subscribed != set(keys)
                    or any(
                        len(group.keys) > 1
                        and not self.large_value_keys.isdisjoint(group.keys)
                        for group in self._groups
                    )
                )
                if rebuild:
                    self._retire_groups()
                    if not await self._cleanup_retired_groups() or not self._current(
                        generation
                    ):
                        return [MISSING_STATE] * len(keys)
                    chunks = self.state_read_batches(keys)
                    if rebase:
                        # Reusing a previous base requires a new listener lifetime.
                        if self.subscription_id in self._used_subscription_ids:
                            await self._close_report_listener()
                            if not await self._ensure_report_listener():
                                return [MISSING_STATE] * len(keys)
                        self._next_subscription_id = self.subscription_id
                        self._group_base_id = self.subscription_id
                    if len(chunks) > MAX_SUBSCRIPTION_ID:
                        raise ValueError("Too many subscription groups")
                    if (
                        len(self._used_subscription_ids) + len(chunks)
                        > MAX_SUBSCRIPTION_ID
                    ):
                        await self._close_report_listener()
                        if not await self._ensure_report_listener():
                            return [MISSING_STATE] * len(keys)
                    if not self._current(generation):
                        return None
                    self._groups = [
                        _SubscriptionGroup(chunk, self._allocate_subscription_id())
                        for chunk in chunks
                    ]
                    self._groups_by_id = {
                        group.subscription_id: group for group in self._groups
                    }
                    self._rebase_requested = False

                values_by_key: dict[StateKey, GrentonRegistrationValue] = {}
                for group in self._groups.copy():
                    if not self._current(generation):
                        return None
                    if required_keys is not None and required_keys.isdisjoint(
                        group.keys
                    ):
                        continue
                    values = await self._register_group(group)
                    if not self._current(generation):
                        return None
                    values_by_key.update(zip(group.keys, values))
                return [values_by_key.get(key, MISSING_STATE) for key in keys]
        finally:
            self._registration_waiters -= 1
            if not self._registration_waiters:
                self._registrations_idle.set()

    async def _register_group(
        self, group: _SubscriptionGroup
    ) -> list[GrentonRegistrationValue]:
        protocol, address = self.protocol, self._report_address
        generation = self._generation
        if not self._current(generation) or protocol is None or address is None:
            return [MISSING_STATE] * len(group.keys)
        group.registered = True
        group.report_address = address
        wire = None
        try:
            wire = await protocol.send_request(
                GrentonCluApiClientRegisterRequest(
                    group.keys,
                    0,
                    subscription_id=group.subscription_id,
                    report_ip=address[0],
                    report_port=address[1],
                )
            )
        except ConnectionError:
            pass
        if (
            not self._current(generation)
            or protocol is not self.protocol
            or wire is None
        ):
            return [MISSING_STATE] * len(group.keys)
        try:
            response = GrentonCluApiClientRegisterResponse(wire, group.keys, self.clu)
            if response.session_id != group.subscription_id:
                raise ValueError("Unexpected subscription ID")
            if len(response.values) != len(group.keys):
                raise ValueError("Incomplete subscription registration reply")
            group.confirmed = True
            return list(response.values)
        except ValueError as error:
            _LOGGER.warning(
                "[%s] Invalid subscription registration reply for ID %d: %s",
                self.log_identity,
                group.subscription_id,
                error,
            )
            return [MISSING_STATE] * len(group.keys)

    async def _deliver_group_report(
        self,
        protocol: GrentonCluApiProtocol,
        group: _SubscriptionGroup,
        values: list[GrentonValue],
    ) -> None:
        if (
            self._current(protocol._generation)
            and self.report_protocol is protocol
            and self._groups_by_id.get(group.subscription_id) is group
            and self.on_subscription_report is not None
        ):
            await self.on_subscription_report(group.keys, values)

    async def fetch_component_states(
        self, keys: list[StateKey]
    ) -> list[GrentonRegistrationValue]:
        """Release scheduling locks between batches so renewals cannot starve."""
        generation = self._generation
        values_by_key: dict[StateKey, GrentonRegistrationValue] = {}
        for chunk in self.state_read_batches(keys):
            while True:
                await self._registrations_idle.wait()
                async with self._registration_lock:
                    if not self._current(generation):
                        return [MISSING_STATE] * len(keys)
                    if self._registration_waiters:
                        continue
                    wire = None
                    protocol = self.protocol
                    key = chunk[0]
                    request: (
                        GrentonCluApiGetValueRequest | GrentonCluApiFetchValuesRequest
                    )
                    if (
                        len(chunk) == 1
                        and key in self.large_value_keys
                        and isinstance(key, GrentonCluStateAttributeKey)
                    ):
                        try:
                            request = GrentonCluApiGetValueRequest(key)
                        except ValueError as error:
                            _LOGGER.warning(
                                "[%s] Invalid direct read target: %s",
                                self.log_identity,
                                error,
                            )
                            break
                    else:
                        request = GrentonCluApiFetchValuesRequest(chunk)
                    if protocol is not None:
                        try:
                            async with self._action_lock:
                                if self._current(generation):
                                    wire = await protocol.send_request(request)
                        except ConnectionError:
                            pass
                    if not self._current(generation):
                        return [MISSING_STATE] * len(keys)
                    values: list[GrentonRegistrationValue] = [MISSING_STATE] * len(
                        chunk
                    )
                    if wire is not None:
                        try:
                            response = (
                                GrentonCluApiGetValueResponse(
                                    wire, request.key, self.clu
                                )
                                if isinstance(request, GrentonCluApiGetValueRequest)
                                else GrentonCluApiFetchValuesResponse(
                                    wire, chunk, self.clu
                                )
                            )
                            values = list(response.values)
                        except ValueError as error:
                            _LOGGER.warning(
                                "[%s] Invalid %s reply: %s",
                                self.log_identity,
                                "get"
                                if isinstance(request, GrentonCluApiGetValueRequest)
                                else "fetchValues",
                                error,
                            )
                    values_by_key.update(zip(chunk, values))
                    break
            await asyncio.sleep(0)
        return [values_by_key.get(key, MISSING_STATE) for key in keys]

    async def poll_component_states(
        self, keys: list[StateKey]
    ) -> list[GrentonRegistrationValue]:
        return await self.fetch_component_states(keys)

    async def execute_action(self, action: GrentonAction) -> bool:
        if self._closed or self._closing or self.protocol is None:
            return False
        request = GrentonCluApiActionRequest.from_action(action)
        generation = self._generation
        async with self._action_lock:
            if not self._current(generation) or self.protocol is None:
                return False
            wire = await self.protocol.send_request(request)
        return wire is not None


class GrentonCluApiProtocol(asyncio.DatagramProtocol):
    """One owned UDP endpoint, its reply waiters and notification tasks."""

    def __init__(self, api: GrentonCluApi, *, report_listener: bool = False):
        self.api = api
        self.report_listener = report_listener
        self._generation = api._generation
        self.transport: asyncio.DatagramTransport | None = None
        self._pending: dict[str, asyncio.Future[str]] = {}
        self._response_timeout = 5.0
        self.health = CluConnectionHealth()
        self._local_address = "unbound"
        self._sent_requests = 0
        self._received_replies = 0
        self._received_reports = 0
        self._received_report_datagrams = 0
        self._discarded_packets: Counter[str] = Counter()
        self._last_udp_error: str | None = None
        self._last_udp_error_at: float | None = None
        self.closed = False
        self._report_tasks: set[asyncio.Task] = set()
        self.subscription_keys: list[StateKey] | None = None
        self.subscription_callback: (
            Callable[[list[GrentonValue]], Awaitable[None]] | None
        ) = None

    def diagnostic_context(self) -> str:
        """Identify this socket even if another socket still receives replies."""
        role = "reports" if self.report_listener else "control"
        discarded = (
            ",".join(
                f"{reason}:{count}" for reason, count in self._discarded_packets.items()
            )
            or "none"
        )
        pending = sum(not future.done() for future in self._pending.values())
        udp_error = self._last_udp_error or "none"
        if self._last_udp_error_at is not None:
            udp_error += (
                f" ({max(0.0, monotonic() - self._last_udp_error_at):.1f}s ago)"
            )
        return (
            f"endpoint={role}; local={self._local_address}; active={self.active}; "
            f"last_endpoint_response={self.health.describe_last_response()}; "
            f"sent={self._sent_requests}, replies={self._received_replies}, reports={self._received_reports}, "
            f"endpoint_timeouts={self.health.request_timeouts}, pending={pending}; "
            f"discarded={discarded}; last_udp_error={udp_error}; "
            f"{self.api.diagnostic_context()}"
        )

    def _record_response(self) -> None:
        self.health.record_response()
        self.api.health.record_response()

    @property
    def active(self) -> bool:
        """A detached socket cannot resume when the same API reconnects."""
        return (
            not self.closed
            and not self.api._closed
            and self._generation == self.api._generation
        )

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        if not self.active:
            transport.close()
            return
        self.transport = cast(asyncio.DatagramTransport, transport)
        address = transport.get_extra_info("sockname")
        if isinstance(address, tuple) and len(address) >= 2:
            self._local_address = f"{address[0]}:{address[1]}"
        _LOGGER.debug("[%s] UDP connection established", self.api.clu.name)

    def close(self) -> None:
        """Stop dispatch synchronously, including before connection_lost runs."""
        if self.closed:
            return
        self.closed = True
        self.subscription_callback = None
        transport, self.transport = self.transport, None
        futures, self._pending = list(self._pending.values()), {}
        for future in futures:
            if not future.done():
                future.set_exception(
                    ConnectionError(
                        f"UDP connection closed for CLU {self.api.clu.name}"
                    )
                )
        for task in self._report_tasks:
            if task is not asyncio.current_task():
                task.cancel()
        if transport is not None:
            transport.close()

    async def wait_closed(self) -> None:
        tasks = [
            task for task in self._report_tasks if task is not asyncio.current_task()
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if addr != (self.api.clu.ip, self.api.clu.port):
            self._discarded_packets["wrong_peer"] += 1
            _LOGGER.debug(
                "[%s] Ignoring datagram from unexpected peer %s", self.api.clu.id, addr
            )
            return
        self._handle_incoming_data(data)

    def _handle_incoming_data(self, data: bytes) -> None:
        if not self.active:
            return
        decrypted = self.api.cipher.decrypt(data)
        if decrypted is None:
            self._discarded_packets["decryption"] += 1
            _LOGGER.warning(
                "[%s] Failed to decrypt CLU message; %s",
                self.api.log_identity,
                self.diagnostic_context(),
            )
            return
        try:
            # PKCS7 padding was removed by the cipher. A direct get reply is
            # an unquoted scalar, so trailing whitespace belongs to its value.
            plaintext = decrypted.decode()
        except UnicodeDecodeError:
            self._discarded_packets["encoding"] += 1
            _LOGGER.warning(
                "[%s] Failed to decode CLU message; %s",
                self.api.log_identity,
                self.diagnostic_context(),
            )
            return
        self._process_response(plaintext)

    def _report_values(self, wire_message: str) -> list[GrentonValue]:
        notification = GrentonCluApiClientReportNotification(
            wire_message, self.subscription_keys, self.api.clu
        )
        if self.subscription_keys is not None and len(notification.values) != len(
            self.subscription_keys
        ):
            raise ValueError("Incomplete subscription report")
        return notification.values

    async def _deliver_report(self, values: list[GrentonValue]) -> None:
        try:
            if self.active and self.subscription_callback is not None:
                await self.subscription_callback(values)
        except Exception as error:  # noqa: BLE001 - a bad consumer must not break other reports
            _LOGGER.error(
                "[%s] Could not process subscription report: %s", self.api.clu.id, error
            )

    async def _deliver_group_report(self, group, values) -> None:
        try:
            if self.active:
                await self.api._deliver_group_report(self, group, values)
        except Exception as error:  # noqa: BLE001 - one consumer must not stop reports
            _LOGGER.error(
                "[%s] Could not process subscription report: %s",
                self.api.log_identity,
                error,
            )

    def _process_response(self, wire_message: str) -> None:
        if not self.active:
            return
        response = GrentonCluApiMessageParser.parse_response(wire_message)
        if response is None:
            self._discarded_packets["invalid_message"] += 1
            _LOGGER.debug("[%s] Received unsupported message", self.api.clu.name)
            return
        message_id = response.msg_id
        _LOGGER.debug(
            "[%s][%s] Received: %s", self.api.clu.name, message_id, wire_message
        )
        future = self._pending.pop(message_id, None)
        if future is not None and not future.done():
            self._received_replies += 1
            self._record_response()
            future.set_result(wire_message)
            return
        if not response.is_client_report:
            self._discarded_packets["unmatched_reply"] += 1
            return
        self._received_report_datagrams += 1
        try:
            if self.report_listener:
                header = response.payload.split(":", 2)
                try:
                    subscription_id = int(header[1])
                except (ValueError, IndexError):
                    raise ValueError("Invalid clientReport subscription ID") from None
                group = self.api._groups_by_id.get(subscription_id)
                if group is None or not group.registered:
                    reason = (
                        "retired_subscription"
                        if subscription_id in self.api._used_subscription_ids
                        else "unknown_subscription"
                    )
                    self._discarded_packets[reason] += 1
                    return
                notification = GrentonCluApiClientReportNotification(
                    wire_message, group.keys, self.api.clu
                )
                values = notification.values
                if len(values) != len(group.keys):
                    raise ValueError("Incomplete subscription report")
            else:
                if self.subscription_callback is None:
                    self._discarded_packets["unmatched_reply"] += 1
                    return
                values = self._report_values(wire_message)
        except ValueError as error:
            self._discarded_packets["invalid_report"] += 1
            _LOGGER.error(
                "[%s] Failed to parse client report: %s; %s",
                self.api.log_identity,
                error,
                self.diagnostic_context(),
            )
            return
        task = asyncio.create_task(
            self._deliver_group_report(group, values)
            if self.report_listener
            else self._deliver_report(values)
        )
        self._received_reports += 1
        self._record_response()
        self._report_tasks.add(task)
        task.add_done_callback(self._report_tasks.discard)

    def _can_send(self, request: GrentonCluApiRequest) -> bool:
        return (
            self.active
            and self.transport is not None
            and (
                not self.api._closing
                or isinstance(request, GrentonCluApiClientDestroyRequest)
            )
        )

    def _is_large_read(self, request: GrentonCluApiRequest) -> bool:
        return isinstance(
            request, (GrentonCluApiFetchValuesRequest, GrentonCluApiGetValueRequest)
        ) and (not self.api.large_value_keys.isdisjoint(request.keys))

    async def send_request(self, request: GrentonCluApiRequest) -> str | None:
        """Pace requests and keep large reads exclusive until their reply."""
        if not self._can_send(request):
            return None
        queued_at = asyncio.get_running_loop().time()
        async with self.api._request_gate.access(
            exclusive=self._is_large_read(request)
        ):
            return await self._send_request(request, queued_at)

    async def _send_request(
        self, request: GrentonCluApiRequest, queued_at: float
    ) -> str | None:
        if not self._can_send(request):
            return None
        msg_id = request.msg_id
        encrypted = self.api.cipher.encrypt(request.raw.encode())
        if encrypted is None:
            _LOGGER.error(
                "[%s][%s] Failed to encrypt request; %s",
                self.api.log_identity,
                msg_id,
                self.diagnostic_context(),
            )
            return None
        future: asyncio.Future[str] | None = None
        loop = asyncio.get_running_loop()
        sent_at: float | None = None
        reports_at_send = self._received_reports
        replies_at_send = self._received_replies
        other_requests_at_send = 0
        try:
            async with self.api._send_lock:
                delay = self.api._next_send_at - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                transport = self.transport
                if not self._can_send(request) or transport is None:
                    return None
                if msg_id in self._pending:
                    _LOGGER.warning(
                        "[%s][%s] Duplicate in-flight request ID; %s",
                        self.api.log_identity,
                        msg_id,
                        self.diagnostic_context(),
                    )
                    return None
                # Do not accept stale replies while waiting for the send gate.
                reports_at_send = self._received_reports
                replies_at_send = self._received_replies
                other_requests_at_send = sum(
                    not pending.done() for pending in self._pending.values()
                )
                future = loop.create_future()
                self._pending[msg_id] = future
                transport.sendto(encrypted, (self.api.clu.ip, self.api.clu.port))
                self._sent_requests += 1
                sent_at = loop.time()
                self.api._next_send_at = loop.time() + MIN_SEND_INTERVAL
            _LOGGER.debug("[%s][%s] Sent: %s", self.api.clu.name, msg_id, request.raw)
            return await asyncio.wait_for(future, timeout=self._response_timeout)
        except TimeoutError:
            self.api.health.request_timeouts += 1
            self.health.request_timeouts += 1
            if isinstance(
                request, (GrentonCluApiFetchValuesRequest, GrentonCluApiGetValueRequest)
            ):
                large = self._is_large_read(request)
                operation = (
                    f"{'large' if large else 'slow'} read ({len(request.keys)} keys)"
                )
                method = (
                    "get"
                    if isinstance(request, GrentonCluApiGetValueRequest)
                    else "fetchValues"
                )
                operation += (
                    f" [method={method}, large={large}, "
                    f"targets={_diagnostic_targets(request.keys)!r}]"
                )
            elif isinstance(request, GrentonCluApiClientRegisterRequest):
                operation = (
                    f"subscription registration ({len(request.keys)} keys) "
                    f"[subscription_id={request.subscription_id}, "
                    f"targets={_diagnostic_targets(request.keys)!r}]"
                )
            elif isinstance(request, GrentonCluApiClientDestroyRequest):
                operation = "subscription destruction"
            elif isinstance(request, GrentonCluApiPingRequest):
                operation = "ping"
            else:
                operation = "action write"
            _LOGGER.warning(
                "[%s][%s] Request timeout during %s after %.2fs "
                "(limit=%.2fs, queued=%.3fs); reports_during_wait=%d, "
                "other_replies_during_wait=%d, other_requests_in_flight_at_send=%d; %s",
                self.api.log_identity,
                msg_id,
                operation,
                loop.time() - sent_at if sent_at is not None else 0,
                self._response_timeout,
                sent_at - queued_at if sent_at is not None else loop.time() - queued_at,
                self._received_reports - reports_at_send,
                self._received_replies - replies_at_send,
                other_requests_at_send,
                self.diagnostic_context(),
            )
            return None
        except (ConnectionError, asyncio.CancelledError):
            raise
        except Exception as error:  # noqa: BLE001 - contain transport errors; never replay writes
            _LOGGER.error(
                "[%s][%s] Failed to send request: %s: %s; %s",
                self.api.log_identity,
                msg_id,
                type(error).__name__,
                error,
                self.diagnostic_context(),
            )
            return None
        finally:
            if future is not None:
                if self._pending.get(msg_id) is future:
                    self._pending.pop(msg_id)
                if not future.done():
                    future.cancel()
                elif not future.cancelled():
                    # A close during send/pacing can fail the waiter before it
                    # is awaited. Always retrieve its exception during cleanup.
                    future.exception()

    def error_received(self, exc: Exception) -> None:
        self._last_udp_error = f"{type(exc).__name__}: {exc}"
        self._last_udp_error_at = monotonic()
        _LOGGER.error(
            "[%s] UDP error: %s; %s",
            self.api.log_identity,
            self._last_udp_error,
            self.diagnostic_context(),
        )

    def connection_lost(self, exc: Exception | None) -> None:
        self.transport = None
        self.close()
        if exc:
            self._last_udp_error = f"{type(exc).__name__}: {exc}"
            self._last_udp_error_at = monotonic()
            _LOGGER.error(
                "[%s] UDP connection lost: %s; %s",
                self.api.log_identity,
                self._last_udp_error,
                self.diagnostic_context(),
            )
        else:
            _LOGGER.debug("[%s] UDP connection closed", self.api.clu.name)
