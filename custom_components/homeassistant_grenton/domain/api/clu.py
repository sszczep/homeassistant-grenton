from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional, Dict, Callable, Awaitable
import logging
import asyncio
import secrets

from ..clu import GrentonClu
from ..encryption import GrentonEncryption
from ..action import GrentonAction
from ...state import GrentonCluStateVariableKey, GrentonCluStateAttributeKey, GrentonValue
from ..cipher import GrentonCipher
from .clu_messages import (
    GrentonCluApiMessageParser,
    GrentonCluApiPingRequest,
    GrentonCluApiClientRegisterRequest,
    GrentonCluApiClientRegisterResponse,
    GrentonCluApiClientReportNotification,
    GrentonCluApiActionRequest,
)

_LOGGER = logging.getLogger(__name__)

# CLU's UDP buffer caps how many keys fit in one clientRegister payload.
# 30 keys is empirically safe; payload + AES padding stays under the MTU.
MAX_KEYS_PER_REGISTER = 30

StateKey = GrentonCluStateVariableKey | GrentonCluStateAttributeKey


@dataclass
class _SubscriptionEndpoint:
    """One UDP socket dedicated to a single sub-subscription (chunk of keys).

    Each chunk gets its own socket because CLU client_report notifications do
    not carry a usable session_id — the only way to know which chunk a report
    belongs to is to receive it on a chunk-specific socket.
    """
    transport: asyncio.DatagramTransport
    protocol: "GrentonCluApiProtocol"
    keys: list[StateKey]
    session_id: int


class GrentonCluApi:
    """Handles all communication with Grenton CLUs via UDP."""

    def __init__(self, clu: GrentonClu, encryption: GrentonEncryption):
        self.clu = clu
        self.encryption = encryption
        self.cipher = GrentonCipher(encryption)

        # Main socket — used for pings and actions only.
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.protocol: Optional[GrentonCluApiProtocol] = None
        self.keep_alive_id = secrets.token_hex(4)

        # One socket per chunk of subscribed keys. Reports arrive on the same
        # socket that registered them, so mapping is implicit.
        self._subscription_endpoints: list[_SubscriptionEndpoint] = []

        # Set by the coordinator; invoked with (keys, values) for every report.
        self.on_subscription_report: Optional[
            Callable[[list[StateKey], list[GrentonValue]], Awaitable[None]]
        ] = None

    async def connect(self) -> bool:
        """Open the main UDP socket used for pings and actions."""
        try:
            loop = asyncio.get_event_loop()

            protocol = GrentonCluApiProtocol(self)
            self.protocol = protocol

            self.transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=('0.0.0.0', 0),
            )

            _LOGGER.debug("[%s] Opened main UDP socket to %s:%d", self.clu.id, self.clu.ip, self.clu.port)
            return True

        except Exception as e:
            _LOGGER.error("[%s] Failed to create main UDP socket to %s:%d: %s",
                          self.clu.id, self.clu.ip, self.clu.port, e)
            return False

    async def disconnect(self) -> None:
        """Close all sockets — main and per-subscription."""
        await self._close_subscription_endpoints()

        if self.transport:
            self.transport.close()
            _LOGGER.debug("[%s] Closed main UDP socket", self.clu.id)
            self.transport = None
        self.protocol = None

    async def _close_subscription_endpoints(self) -> None:
        for endpoint in self._subscription_endpoints:
            try:
                endpoint.transport.close()
            except Exception as e:
                _LOGGER.debug("[%s] Error closing subscription socket sid=%d: %s",
                              self.clu.id, endpoint.session_id, e)
        if self._subscription_endpoints:
            _LOGGER.debug("[%s] Closed %d subscription socket(s)",
                          self.clu.id, len(self._subscription_endpoints))
        self._subscription_endpoints = []

    async def ping(self) -> bool:
        """Send a keep-alive ping on the main socket."""
        if not self.protocol:
            _LOGGER.warning("[%s] No protocol available for ping", self.clu.id)
            return False

        request = GrentonCluApiPingRequest(self.keep_alive_id)
        wire_message = await self.protocol.send_request(request)
        return wire_message is not None

    async def register_component_states(self, keys: list[StateKey]) -> list[GrentonValue] | None:
        """Register state keys as one sub-subscription per chunk of MAX_KEYS_PER_REGISTER.

        Each chunk gets its own UDP socket so that subsequent clientReport
        notifications can be routed back to the right keys without relying on
        any identifier inside the report payload.

        Returns initial values in the same order as the input ``keys``; positions
        for chunks that failed are filled with None.
        """
        if not keys:
            _LOGGER.debug("[%s] No state keys to register", self.clu.id)
            return None

        await self._close_subscription_endpoints()

        chunks = [
            keys[i : i + MAX_KEYS_PER_REGISTER]
            for i in range(0, len(keys), MAX_KEYS_PER_REGISTER)
        ]

        results = await asyncio.gather(*(self._setup_chunk(chunk) for chunk in chunks))
        return [value for chunk_values in results for value in chunk_values]

    async def _setup_chunk(self, chunk: list[StateKey]) -> list[GrentonValue]:
        """Open a dedicated socket, register the chunk, return its initial values."""
        session_id = secrets.randbelow(65535) + 1  # 1..65535, avoid 0
        loop = asyncio.get_event_loop()

        protocol = GrentonCluApiProtocol(self)

        # Closure binds this chunk's keys to incoming reports on this socket.
        async def on_report(values: list[GrentonValue]) -> None:
            if self.on_subscription_report is not None:
                await self.on_subscription_report(chunk, values)
        protocol.subscription_callback = on_report

        try:
            transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=('0.0.0.0', 0),
            )
        except Exception as e:
            _LOGGER.error("[%s] Failed to create subscription socket (sid=%d): %s",
                          self.clu.id, session_id, e)
            return [None] * len(chunk)

        endpoint = _SubscriptionEndpoint(transport, protocol, chunk, session_id)
        self._subscription_endpoints.append(endpoint)
        _LOGGER.debug("[%s] Opened subscription socket sid=%d for %d key(s)",
                      self.clu.id, session_id, len(chunk))

        request = GrentonCluApiClientRegisterRequest(chunk, session_id, secrets.token_hex(4))
        wire = await protocol.send_request(request)
        if wire is None:
            return [None] * len(chunk)
        try:
            return GrentonCluApiClientRegisterResponse(wire).values
        except ValueError as e:
            _LOGGER.error("[%s] Failed to parse register response (sid=%d): %s",
                          self.clu.id, session_id, e)
            return [None] * len(chunk)

    async def execute_action(self, action: GrentonAction) -> bool:
        """Execute an action on the CLU via the main socket."""
        if not self.protocol:
            _LOGGER.warning("[%s] No protocol available for action execution", self.clu.id)
            return False

        request = GrentonCluApiActionRequest.from_action(action)
        wire_message = await self.protocol.send_request(request)

        return wire_message is not None


class GrentonCluApiProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler for one socket — main or subscription.

    Each instance owns its transport (set in connection_made) and routes
    incoming clientReport notifications to its ``subscription_callback``.
    Subscription sockets have a callback that knows their chunk's keys via
    closure; the main socket leaves the callback unset.
    """

    def __init__(self, api: GrentonCluApi):
        self.api = api
        self.transport: Optional[asyncio.DatagramTransport] = None
        self._pending: Dict[str, asyncio.Future[str]] = {}
        self._pending_lock = asyncio.Lock()
        self._response_timeout = 5.0
        self.subscription_callback: Optional[
            Callable[[list[GrentonValue]], Awaitable[None]]
        ] = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport
        _LOGGER.debug("[%s] UDP connection established", self.api.clu.name)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._handle_incoming_data(data)

    def _handle_incoming_data(self, data: bytes) -> None:
        """Handle incoming UDP data from the CLU."""
        decrypted = self.api.cipher.decrypt(data)
        if decrypted is None:
            _LOGGER.warning("[%s] Failed to decrypt message: %s",
                            self.api.clu.name, data.hex())
            return

        try:
            plaintext = decrypted.decode().strip()
        except Exception:
            _LOGGER.warning("[%s] Failed to decode decrypted message: %s",
                            self.api.clu.name, decrypted.hex())
            return

        if not GrentonCluApiMessageParser.is_valid_response(plaintext):
            _LOGGER.debug("[%s] Received unsupported message: %s",
                          self.api.clu.name, plaintext)
            return

        self._process_response(plaintext)

    def _process_response(self, wire_message: str) -> None:
        """Process a response message from the CLU."""
        parts = wire_message.split(":", 3)
        if len(parts) != 4:
            _LOGGER.warning("[%s] Invalid wire message format", self.api.clu.name)
            return

        message_id = parts[2].lower()
        _LOGGER.debug("[%s][%s] Received: %s", self.api.clu.name, message_id, wire_message)

        async def _complete() -> None:
            async with self._pending_lock:
                fut = self._pending.pop(message_id, None)

            if fut and not fut.done():
                fut.set_result(wire_message)
            else:
                if GrentonCluApiMessageParser.is_client_report(wire_message):
                    if self.subscription_callback:
                        try:
                            notification = GrentonCluApiClientReportNotification(wire_message)
                        except ValueError as e:
                            _LOGGER.error("[%s] Failed to parse client report: %s",
                                          self.api.clu.name, e)
                            return
                        await self.subscription_callback(notification.values)
                    else:
                        _LOGGER.debug("[%s][%s] Received report but no callback registered",
                                      self.api.clu.name, message_id)
                else:
                    _LOGGER.debug("[%s][%s] Response received with no pending request",
                                  self.api.clu.name, message_id)

        asyncio.create_task(_complete())

    async def send_request(self, request: Any, message_id: Optional[str] = None) -> Optional[str]:
        """Send a request via this socket's transport and wait for a matching response."""
        if not self.transport:
            _LOGGER.error("[%s] Transport not ready", self.api.clu.name)
            return None

        msg_id = request.msg_id
        payload = request.raw.encode()
        encrypted = self.api.cipher.encrypt(payload)

        if encrypted is None:
            _LOGGER.error("[%s] Failed to encrypt request", self.api.clu.name)
            return None

        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

        async with self._pending_lock:
            self._pending[msg_id] = future

        try:
            self.transport.sendto(encrypted, (self.api.clu.ip, self.api.clu.port))
            _LOGGER.debug("[%s][%s] Sent: %s", self.api.clu.name, msg_id, request.raw)
        except Exception as e:
            async with self._pending_lock:
                self._pending.pop(msg_id, None)
            _LOGGER.error("[%s][%s] Failed to send request: %s",
                          self.api.clu.name, msg_id, e)
            return None

        try:
            return await asyncio.wait_for(future, timeout=self._response_timeout)
        except asyncio.TimeoutError:
            async with self._pending_lock:
                self._pending.pop(msg_id, None)
            _LOGGER.warning("[%s][%s] Request timeout", self.api.clu.name, msg_id)
            return None
        except Exception:
            async with self._pending_lock:
                self._pending.pop(msg_id, None)
            raise

    def error_received(self, exc: Exception) -> None:
        _LOGGER.error("[%s] UDP error: %s", self.api.clu.name, exc)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        if exc:
            _LOGGER.error("[%s] UDP connection lost: %s", self.api.clu.name, exc)
        else:
            _LOGGER.debug("[%s] UDP connection closed", self.api.clu.name)

        async def _fail_pending() -> None:
            async with self._pending_lock:
                futures = list(self._pending.values())
                self._pending.clear()

            for fut in futures:
                if not fut.done():
                    fut.set_exception(ConnectionError(
                        f"UDP connection closed for CLU {self.api.clu.name}"))

        asyncio.create_task(_fail_pending())
