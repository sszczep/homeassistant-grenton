"""Shared-listener reports cannot consume control-socket keepalive replies."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from test_clu_lifecycle import fixture
from test_clu_protocol_lifecycle import socket_factory, tick

from custom_components.homeassistant_grenton.state import GrentonCluStateVariableKey


async def pending_ping(protocol):
    async def wait():
        while not protocol._pending:
            await tick()
        message_id, waiter = next(iter(protocol._pending.items()))
        return message_id, waiter

    return await asyncio.wait_for(wait(), 1)


def report(protocol, api, value):
    subscription_id = api._groups[0].subscription_id
    protocol.datagram_received(
        f"resp:{api.clu.ip}:00000000:clientReport:{subscription_id}:{{{value}}}".encode(),
        (api.clu.ip, api.clu.port),
    )


def acknowledge(protocol, api, message_id):
    protocol.datagram_received(
        f"resp:{api.clu.ip}:{message_id}:pong".encode(),
        (api.clu.ip, api.clu.port),
    )


def test_reports_do_not_consume_control_ping_waiter_and_ack_completes(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        sockets = []
        with socket_factory(api, sockets):
            await api.connect()
            key = GrentonCluStateVariableKey("temperature")
            await api.register_component_states([key])
            control, listener = api.protocol, api.report_protocol
            api.transport.reply = False
            api.on_subscription_report = AsyncMock()
            ping = asyncio.create_task(api.ping())
            message_id, waiter = await pending_ping(control)
            received_before = control._received_replies
            for value in range(32):
                report(listener, api, value)
                await tick()
                assert control._pending[message_id] is waiter
                assert not waiter.done() and not ping.done()
            acknowledge(control, api, message_id)
            assert await ping
            assert not control._pending
            assert control._received_replies == received_before + 1
            assert listener._received_reports == 32
            assert api.on_subscription_report.await_count == 32
            assert api.on_subscription_report.await_args.args == ([key], [31])
            assert api.health.request_timeouts == 0
            assert not control._discarded_packets and not listener._discarded_packets
            assert len(sockets) == 2 and not api.report_transport.sent
            api.transport.reply = True
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("finish", ["timeout", "cancel"])
def test_missing_control_ack_amid_reports_keeps_listener_and_ignores_late_ack(
    tmp_path, caplog, finish
):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        sockets = []
        with socket_factory(api, sockets):
            await api.connect()
            await api.register_component_states([GrentonCluStateVariableKey("value")])
            groups = api._groups.copy()
            control, listener = api.protocol, api.report_protocol
            transport = api.transport
            transport.reply = False
            control._response_timeout = 0.2
            api.on_subscription_report = AsyncMock()
            before = [len(socket.sent) for socket in sockets]
            ping = asyncio.create_task(api.ping())
            message_id, waiter = await pending_ping(control)
            for value in range(3):
                report(listener, api, value)
                await tick()
            assert not waiter.done() and not ping.done()
            assert api.on_subscription_report.await_count == 3
            if finish == "timeout":
                assert not await ping
                assert (
                    api.health.request_timeouts == control.health.request_timeouts == 1
                )
                message = next(
                    record.getMessage()
                    for record in caplog.records
                    if "Request timeout during ping" in record.getMessage()
                )
                assert "reports_during_wait=0" in message
                assert "other_replies_during_wait=0" in message
            else:
                ping.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await ping
                assert (
                    api.health.request_timeouts == control.health.request_timeouts == 0
                )
            assert not control._pending
            assert control.active and listener.active and not transport.closed
            assert api._groups == groups
            assert [
                len(socket.sent) - prior for socket, prior in zip(sockets, before)
            ] == [1, 0]
            last_seen = api.health.last_seen
            acknowledge(control, api, message_id)
            await tick()
            assert control._discarded_packets["unmatched_reply"] == 1
            assert api.health.last_seen is last_seen
            assert api.on_subscription_report.await_count == 3
            transport.reply = True
            control._response_timeout = 5
            assert await api.ping()
            assert api._groups == groups
            assert len(sockets) == 2 and not api.report_transport.closed
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())
