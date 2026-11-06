"""Fault injection for UDP ownership, request correlation and independent timers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from test_clu_lifecycle import fixture
from test_clu_scripts import make_entry, make_hass
from test_clu_state import coordinator, make_clu

from custom_components.homeassistant_grenton.domain.action import GrentonActionAttribute
from custom_components.homeassistant_grenton.domain.api.clu import GrentonCluApiProtocol
from custom_components.homeassistant_grenton.domain.api.clu_messages import (
    GrentonCluApiPingRequest,
)
from custom_components.homeassistant_grenton.domain.enums import GrentonActionEventType
from custom_components.homeassistant_grenton.domain.lua_arguments import (
    split_lua_arguments,
)
from custom_components.homeassistant_grenton.domain.state_object import (
    GrentonVariableValueObject,
)
from custom_components.homeassistant_grenton.state import (
    GrentonCluStateVariableKey,
)


async def tick():
    future = asyncio.get_running_loop().create_future()
    asyncio.get_running_loop().call_soon(future.set_result, None)
    await future


class Socket:
    """A local fake transport with asynchronous close/reply callbacks."""

    def __init__(self, protocol, *, reply=True, port=12345):
        self.protocol = protocol
        self.reply = reply
        self.sent = []
        self.closed = False
        self.close_calls = 0
        self.port = port
        protocol.connection_made(self)

    def is_closing(self):
        return self.closed

    def close(self):
        self.close_calls += 1
        if not self.closed:
            self.closed = True
            asyncio.get_running_loop().call_soon(self.protocol.connection_lost, None)

    def get_extra_info(self, name):
        return ("127.0.0.1", self.port)

    def sendto(self, data, addr):
        assert not self.closed
        raw = data.decode()
        self.sent.append((raw, asyncio.get_running_loop().time()))
        if not self.reply:
            return
        _, _, message_id, payload = raw.split(":", 3)
        if payload.startswith("SYSTEM:fetchValues("):
            keys = payload.removeprefix("SYSTEM:fetchValues(").removesuffix(")")
            count = len(split_lua_arguments(keys[1:-1]))
            payload = f"values:{{{','.join(['1'] * count)}}}"
        elif payload.startswith("SYSTEM:clientRegister"):
            arguments = split_lua_arguments(
                payload.removeprefix("SYSTEM:clientRegister(").removesuffix(")")
            )
            subscription_id = arguments[2]
            count = len(split_lua_arguments(arguments[3][1:-1]))
            payload = f"clientReport:{subscription_id}:{{{','.join(['1'] * count)}}}"
        elif payload.startswith("SYSTEM:clientDestroy"):
            payload = split_lua_arguments(
                payload.removeprefix("SYSTEM:clientDestroy(").removesuffix(")")
            )[2]
        elif ":get(" in payload:
            payload = "1"
        else:
            payload = "pong"
        asyncio.get_running_loop().call_soon(
            self.protocol._process_response,
            f"resp:{addr[0]}:{message_id}:{payload}",
        )


def socket_factory(api, sockets, *, reply=True):
    api.cipher = SimpleNamespace(
        encrypt=lambda value: value, decrypt=lambda value: value
    )

    async def create(factory, **kwargs):
        protocol = factory()
        transport = Socket(protocol, reply=reply, port=12345 + len(sockets))
        sockets.append(transport)
        await tick()
        return transport, protocol

    return patch.object(
        asyncio.get_running_loop(), "create_datagram_endpoint", side_effect=create
    )


@pytest.mark.parametrize("subscription", [False, True])
def test_cancelling_socket_creation_closes_a_transport_bound_before_return(
    tmp_path, subscription
):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        sockets, started = [], asyncio.Event()

        async def create(factory, **kwargs):
            protocol = factory()
            sockets.append(Socket(protocol))
            started.set()
            await asyncio.Future()

        with patch.object(
            asyncio.get_running_loop(), "create_datagram_endpoint", side_effect=create
        ):
            operation = api._ensure_report_listener() if subscription else api.connect()
            task = asyncio.create_task(operation)
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert sockets[0].closed and sockets[0].close_calls == 1
            assert not api._opening_protocols and not api._groups
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_concurrent_connect_creates_one_socket_and_disconnect_finishes_pending_requests(
    tmp_path,
):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        sockets = []
        with socket_factory(api, sockets, reply=False):
            assert await asyncio.gather(api.connect(), api.connect()) == [True, True]
            assert len(sockets) == 1
            protocol = api.protocol
            request = asyncio.create_task(
                protocol.send_request(GrentonCluApiPingRequest("00000001"))
            )
            await tick()
            assert protocol._pending
            await api.disconnect()
            assert not protocol._pending and protocol.closed
            with pytest.raises(ConnectionError):
                await asyncio.wait_for(request, 0.5)
            await api.disconnect()
            assert sockets[0].close_calls == 1
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_duplicate_request_id_does_not_replace_or_remove_the_original_waiter(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        sockets = []
        with socket_factory(api, sockets, reply=False):
            await api.connect()
            protocol = api.protocol
            first = asyncio.create_task(
                protocol.send_request(GrentonCluApiPingRequest("00000001"))
            )
            await tick()
            assert (
                await protocol.send_request(GrentonCluApiPingRequest("00000001"))
                is None
            )
            assert len(sockets[0].sent) == 1 and not first.done()
            protocol._process_response("resp:192.0.2.1:00000001:pong")
            assert (await first).endswith(":pong")
            assert not protocol._pending
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_reply_before_queued_request_is_sent_cannot_satisfy_it(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        sockets = []
        with socket_factory(api, sockets, reply=False):
            await api.connect()
            protocol = api.protocol
            async with api._send_lock:
                task = asyncio.create_task(
                    protocol.send_request(GrentonCluApiPingRequest("00000001"))
                )
                await tick()
                protocol._process_response("resp:192.0.2.1:00000001:stale")
                assert not protocol._pending and not sockets[0].sent
            await tick()
            assert not task.done()
            protocol._process_response("resp:192.0.2.1:00000001:fresh")
            assert (await task).endswith(":fresh")
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_disconnect_cancels_notification_tasks_and_ignores_late_reports(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        sockets, started, published = [], asyncio.Event(), []

        async def report(values):
            started.set()
            await asyncio.Future()
            published.append(values)

        with socket_factory(api, sockets):
            await api.connect()
            protocol = api.protocol
            protocol.subscription_keys = [GrentonCluStateVariableKey("a")]
            protocol.subscription_callback = report
            protocol._process_response("resp:192.0.2.1:00000000:clientReport:0:{1}")
            await started.wait()
            await api.disconnect()
            protocol._process_response("resp:192.0.2.1:00000000:clientReport:0:{2}")
            assert not protocol._report_tasks and not published
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_listener_loss_recreates_only_listener_while_control_socket_is_retained(
    tmp_path,
):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        sockets = []
        keys = [GrentonCluStateVariableKey(str(i)) for i in range(31)]
        with socket_factory(api, sockets):
            assert await api.connect()
            assert await api.register_component_states(keys) == [1] * 31
            control, listener = api.transport, api.report_transport
            assert len(sockets) == 2
            listener.close()
            await tick()
            assert await api.register_component_states(keys) == [1] * 31
            assert api.transport is control and api.report_transport is not listener
            assert len(sockets) == 3
            assert all(group.confirmed for group in api._groups)
            assert await api.register_component_states([]) == []
            assert not api._groups
            await api.disconnect()
            assert all(socket.closed for socket in sockets)
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_lost_main_socket_recovers_on_keepalive_but_timeouts_do_not_create_sockets(
    tmp_path,
):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        sockets = []
        with socket_factory(api, sockets):
            assert await api.connect()
            sockets[0].close()
            await tick()
            assert await api.ping()
            assert len(sockets) == 2
            sockets[-1].reply = False
            api.protocol._response_timeout = 0
            assert not await api.ping()
            assert not await api.ping()
            assert len(sockets) == 2
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_cancelled_queued_action_cannot_send_after_disconnect_and_reconnect(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        sockets = []
        action = GrentonActionAttribute(
            "clu1", "Lamp", GrentonActionEventType.ON, "1", "0"
        )
        with socket_factory(api, sockets):
            await api.connect()
            await api._action_lock.acquire()
            task = asyncio.create_task(api.execute_action(action))
            await tick()
            await api.disconnect()
            await api.connect()
            api._action_lock.release()
            assert not await task
            assert not any(socket.sent for socket in sockets)
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("register", [False, True])
def test_stalled_clu_does_not_delay_other_clus_periodic_work(tmp_path, register):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu1"), make_clu("clu2")])
        for clu_id in ("clu1", "clu2"):
            coord._realtime_keys[clu_id].add(GrentonCluStateVariableKey("value"))
        calls, twice = {"clu1": 0, "clu2": 0}, asyncio.Event()
        clock = 0.0

        async def operation(clu_id):
            calls[clu_id] += 1
            if clu_id == "clu1":
                await asyncio.Future()
            if calls[clu_id] == 2:
                twice.set()

        async def sleep(interval):
            nonlocal clock
            clock += interval
            await tick()

        setattr(coord, "_send_register" if register else "_send_ping", operation)
        with (
            patch("asyncio.sleep", side_effect=sleep),
            patch(
                "custom_components.homeassistant_grenton.coordinator.monotonic",
                side_effect=lambda: clock,
            ),
        ):
            task = asyncio.create_task(
                coord._register_loop() if register else coord._ping_loop()
            )
            try:
                await asyncio.wait_for(twice.wait(), 0.5)
                assert calls["clu1"] == 1 and calls["clu2"] >= 2
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_poll_age_is_measured_from_read_start_and_shutdown_discards_late_values(
    tmp_path,
):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        state = GrentonVariableValueObject("clu1", "", "temperature")
        coord.register_component_state(state, read_mode="slow")
        clock = 0

        async def read(keys):
            nonlocal clock
            clock = 1000
            return [22]

        api.poll_component_states = AsyncMock(side_effect=read)
        with patch(
            "custom_components.homeassistant_grenton.coordinator.monotonic",
            side_effect=lambda: clock,
        ):
            await coord._send_slow_poll("clu1")
            assert not coord.is_state_fresh(state)
        before = coord.state.get_value_for_component(state)

        async def read_after_stop(keys):
            coord._stopping = True
            return [99]

        api.poll_component_states.side_effect = read_after_stop
        coord.async_set_updated_data = Mock()
        assert await coord._send_slow_poll("clu1") == set()
        assert coord.state.get_value_for_component(state) == before
        coord.async_set_updated_data.assert_not_called()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_wrong_peer_cannot_update_state(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        api.cipher = Mock()
        protocol = GrentonCluApiProtocol(api)
        protocol.datagram_received(b"unrelated", ("192.0.2.99", api.clu.port))
        protocol.datagram_received(b"unrelated", (api.clu.ip, api.clu.port + 1))
        api.cipher.decrypt.assert_not_called()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_repeated_load_and_unload_leaves_no_live_sockets_or_waiters(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        sockets = []
        keys = [GrentonCluStateVariableKey(str(i)) for i in range(31)]
        with socket_factory(api, sockets):
            for _ in range(10):
                assert await api.connect()
                assert await api.register_component_states(keys) == [1] * 31
                await api.disconnect()
                await tick()
                assert not api._opening_protocols and not api._groups
                assert api.transport is None and api.protocol is None
                assert all(
                    socket.closed
                    and not socket.protocol._pending
                    and not socket.protocol._report_tasks
                    for socket in sockets
                )
            assert len(sockets) == 20
            assert all(socket.close_calls == 1 for socket in sockets)
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())
