"""Keepalive diagnostics explain socket-local failures without extra traffic."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from test_clu_lifecycle import fixture
from test_clu_protocol_lifecycle import Socket, socket_factory, tick

from custom_components.homeassistant_grenton.domain.api.clu import GrentonCluApiProtocol
from custom_components.homeassistant_grenton.domain.api.clu_messages import (
    GrentonCluApiActionRequest,
    GrentonCluApiPingRequest,
)
from custom_components.homeassistant_grenton.state import GrentonCluStateVariableKey


def test_control_ping_failure_identifies_socket_while_reports_continue_and_recovers_once(
    tmp_path, caplog
):
    async def run():
        clock, sockets = [0], []
        with (
            patch(
                "custom_components.homeassistant_grenton.domain.api.clu_health.monotonic",
                side_effect=lambda: clock[0],
            ),
            caplog.at_level(logging.INFO),
        ):
            hass, _, coord, api = await fixture(tmp_path)
            with socket_factory(api, sockets):
                await api.connect()
                await api.register_component_states(
                    [GrentonCluStateVariableKey(str(i)) for i in range(31)]
                )
                await coord._send_ping(api.clu.id)
                caplog.clear()
                before = [len(socket.sent) for socket in sockets]
                api.transport.reply = False
                api.protocol._response_timeout = 0
                clock[0] = 7
                api.report_protocol._process_response(
                    "resp:192.0.2.1:00000000:clientReport:2:{1}"
                )
                await tick()
                await coord._send_ping(api.clu.id)
                warnings = [
                    record.getMessage()
                    for record in caplog.records
                    if record.levelno == logging.WARNING
                ]
                assert len(warnings) == 2
                timeout, summary = warnings
                for detail in (
                    "Main CLU/clu1",
                    "Request timeout during ping",
                    "limit=0.00s",
                    "queued=",
                    "endpoint=control",
                    "local=127.0.0.1:12345",
                    "remote=192.0.2.1:1234",
                    "last_endpoint_response=",
                    "(7.0s ago)",
                    "last_clu_response=",
                    "(0.0s ago)",
                    "endpoint_timeouts=1",
                    "pending=0",
                    "discarded=none",
                ):
                    assert detail in timeout
                assert "Ping failed (consecutive=1): 0/1 endpoints replied" in summary
                assert (
                    "failed=control: no reply" in summary
                    and "total_timeouts=1" in summary
                )
                assert [
                    len(socket.sent) - prior for socket, prior in zip(sockets, before)
                ] == [1, 0]
                api.transport.reply = True
                api.protocol._response_timeout = 5
                await coord._send_ping(api.clu.id)
                await coord._send_ping(api.clu.id)
                recovered = [
                    record.getMessage()
                    for record in caplog.records
                    if "Ping recovered" in record.getMessage()
                ]
                assert (
                    len(recovered) == 1
                    and "after 1 failed cycle(s): 1/1 endpoints replied" in recovered[0]
                )
                assert coord._ping_failures[api.clu.id] == 0
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())


def test_control_timeout_before_first_reply_shows_never_and_consecutive_failures(
    tmp_path, caplog
):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        sockets = []
        with (
            socket_factory(api, sockets, reply=False),
            caplog.at_level(logging.WARNING),
        ):
            await api.connect()
            api.protocol._response_timeout = 0
            await coord._send_ping(api.clu.id)
            await coord._send_ping(api.clu.id)
            messages = [record.getMessage() for record in caplog.records]
            assert any(
                "endpoint=control" in message
                and "last_endpoint_response=never" in message
                for message in messages
            )
            assert any(
                "Ping failed (consecutive=2): 0/1 endpoints replied" in message
                and "failed=control: no reply" in message
                and "last_clu_response=never" in message
                for message in messages
            )
            assert len(sockets) == 1 and len(sockets[0].sent) == 2
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_timeout_includes_receive_rejections_and_udp_error_without_values(
    tmp_path, caplog
):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        api.cipher = SimpleNamespace(
            encrypt=lambda value: value, decrypt=lambda value: value
        )
        protocol = GrentonCluApiProtocol(api)
        api.protocol = protocol
        socket = Socket(protocol, reply=False)
        peer = (api.clu.ip, api.clu.port)
        secret = "private-value-do-not-log"
        with caplog.at_level(logging.WARNING):
            protocol.datagram_received(b"irrelevant", ("192.0.2.99", api.clu.port))
            api.cipher.decrypt = lambda value: None
            protocol.datagram_received(b"irrelevant", peer)
            api.cipher.decrypt = lambda value: value
            protocol.datagram_received(b"\xff", peer)
            protocol.datagram_received(b"invalid-envelope", peer)
            protocol.datagram_received(b"resp:192.0.2.1:12345678:pong", peer)
            protocol.subscription_callback = AsyncMock()
            protocol.subscription_keys = [GrentonCluStateVariableKey("a")]
            protocol.datagram_received(
                b"resp:192.0.2.1:00000000:clientReport:bad:{}", peer
            )
            protocol.datagram_received(
                f'resp:192.0.2.1:00000000:clientReport:0:{{"{secret}"}}'.encode(), peer
            )
            await tick()
            protocol.error_received(OSError(113, "No route to host"))
            protocol._response_timeout = 0
            await protocol.send_request(
                GrentonCluApiActionRequest(f'Script("{secret}")', "abcdef01")
            )
            message = next(
                record.getMessage()
                for record in caplog.records
                if "Request timeout" in record.getMessage()
            )
            for reason in (
                "wrong_peer",
                "decryption",
                "encoding",
                "invalid_message",
                "unmatched_reply",
                "invalid_report",
            ):
                assert f"{reason}:1" in message
            assert "reports=1" in message
            assert "last_udp_error=OSError: [Errno 113] No route to host" in message
            assert secret not in caplog.text and "Script(" not in caplog.text
            assert len(socket.sent) == 1
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_timeout_separates_send_queue_delay_from_response_wait(tmp_path, caplog):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        with socket_factory(api, [], reply=False), caplog.at_level(logging.WARNING):
            await api.connect()
            protocol = api.protocol
            protocol._response_timeout = 0
            clock = [100.0]
            with patch.object(
                asyncio.get_running_loop(), "time", side_effect=lambda: clock[0]
            ):
                async with api._send_lock:
                    task = asyncio.create_task(
                        protocol.send_request(GrentonCluApiPingRequest("abcdef01"))
                    )
                    await tick()
                    clock[0] = 101.0
                assert await task is None
            message = next(
                record.getMessage()
                for record in caplog.records
                if "Request timeout" in record.getMessage()
            )
            assert "after 0.00s (limit=0.00s, queued=1.000s)" in message
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_cancelling_ping_does_not_log_failure_or_count_timeout(tmp_path, caplog):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        with socket_factory(api, [], reply=False), caplog.at_level(logging.WARNING):
            await api.connect()
            task = asyncio.create_task(coord._send_ping(api.clu.id))
            while not api.protocol._pending:
                await tick()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not api.protocol._pending
            assert not api.health.request_timeouts
            assert not coord._ping_failures[api.clu.id]
            assert not caplog.records
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_failed_socket_open_is_reported_without_extra_ping_attempts(tmp_path, caplog):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        api.connect = AsyncMock(return_value=False)
        with caplog.at_level(logging.WARNING):
            await coord._send_ping(api.clu.id)
            messages = [record.getMessage() for record in caplog.records]
            assert len(messages) == 1
            assert "not attempted: control socket could not be opened" in messages[0]
            assert "Main CLU/clu1" in messages[0]
            assert "remote=192.0.2.1:1234" in messages[0]
            api.connect.assert_awaited_once()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_control_exception_identifies_ping_failure_without_probing_listener(
    tmp_path, caplog
):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        with socket_factory(api, []), caplog.at_level(logging.WARNING):
            await api.connect()
            await api.register_component_states([GrentonCluStateVariableKey("a")])
            listener = api.report_transport
            original = api.protocol.send_request
            api.protocol.send_request = AsyncMock(
                side_effect=ConnectionError("Socket closed while waiting")
            )
            await coord._send_ping(api.clu.id)
            message = next(
                record.getMessage()
                for record in caplog.records
                if "Ping failed" in record.getMessage()
            )
            assert (
                "0/1 endpoints replied" in message
                and "failed=control: no reply" in message
            )
            assert api.health.request_timeouts == 0 and not listener.sent
            api.protocol.send_request = original
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())
