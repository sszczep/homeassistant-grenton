"""Bounded subscription work and socket ownership across Home Assistant stops."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import HomeAssistantError
from test_clu_scripts import make_entry, make_hass
from test_clu_state import coordinator, make_clu

from custom_components.homeassistant_grenton import (
    async_setup_entry,
    async_unload_entry,
)
from custom_components.homeassistant_grenton.domain.api.clu import (
    GrentonCluApiProtocol,
)
from custom_components.homeassistant_grenton.domain.api.clu_messages import (
    GrentonCluApiClientDestroyRequest,
    GrentonCluApiClientRegisterRequest,
    GrentonCluApiPingRequest,
)
from custom_components.homeassistant_grenton.domain.state_object import (
    GrentonVariableValueObject,
)
from custom_components.homeassistant_grenton.state import (
    MISSING_STATE,
    GrentonCluStateVariableKey,
)


async def fixture(tmp_path):
    entry = make_entry()
    hass = await make_hass(tmp_path, [entry])
    coord = coordinator(hass, entry, [make_clu("clu1")])
    return hass, entry, coord, coord._apis["clu1"]


def synthetic_subscription(api, values):
    stats = {"active": 0, "peak": 0, "requests": []}

    async def read(request):
        stats["requests"].append(request)
        if isinstance(request, GrentonCluApiClientDestroyRequest):
            return f"resp:192.0.2.1:{request.msg_id}:{request.subscription_id}"
        stats["active"] += 1
        stats["peak"] = max(stats["peak"], stats["active"])
        await asyncio.sleep(0)
        stats["active"] -= 1
        payload = ",".join(json.dumps(values[key]) for key in request.keys)
        return (
            f"resp:192.0.2.1:{request.msg_id}:"
            f"clientReport:{request.subscription_id}:{{{payload}}}"
        )

    api.transport = Mock()
    api.transport.is_closing.return_value = False
    api.protocol = SimpleNamespace(
        send_request=AsyncMock(side_effect=read),
        closed=False,
        active=True,
        transport=api.transport,
    )
    api.report_transport = Mock()
    api.report_transport.is_closing.return_value = False
    api.report_protocol = SimpleNamespace(
        closed=False,
        active=True,
        transport=api.report_transport,
    )
    api._report_address = ("127.0.0.1", 40001)
    api._ensure_report_listener = AsyncMock(return_value=True)
    return stats


def test_pack_ordinary_values_across_schedules_and_only_refresh_required_groups(
    tmp_path,
):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        keys = [GrentonCluStateVariableKey(str(i)) for i in range(61)]
        large = {keys[29], keys[60]}
        api.large_value_keys = large
        values = {
            key: "Y0" * 672 + "+00:30" if key in large else index
            for index, key in enumerate(keys)
        }
        stats = synthetic_subscription(api, values)
        assert await api.register_component_states(keys) == list(values.values())
        assert stats["peak"] == 1
        groups = api._groups.copy()
        ids = [group.subscription_id for group in groups]
        assert [len(group.keys) for group in groups] == [30, 29, 1, 1]
        assert len(set(ids)) == 4
        control, listener = api.transport, api.report_transport
        stats["requests"].clear()
        selected = {keys[0], keys[29]}
        result = await api.register_component_states(keys, required_keys=selected)
        assert [request.subscription_id for request in stats["requests"]] == [
            ids[0],
            ids[2],
        ]
        assert result[29] == values[keys[29]]
        assert result[30] == values[keys[30]]  # Same ordinary group is returned whole.
        assert result[31] is MISSING_STATE
        assert result[60] is MISSING_STATE
        assert [group.subscription_id for group in api._groups] == ids
        assert await api.register_component_states(keys) == list(values.values())
        assert api.transport is control and api.report_transport is listener
        await coord.async_shutdown()
        for transport in (control, listener):
            transport.close.assert_called_once()
        await hass.async_stop()

    asyncio.run(run())


def test_coordinator_targeted_read_preserves_unrelated_cached_state(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        states = [GrentonVariableValueObject("clu1", "", str(i)) for i in range(61)]
        for state in states:
            coord.register_component_state(state)
        keys = coord.state.clus["clu1"].get_subscription_order()
        values = dict(zip(keys, range(61)))
        stats = synthetic_subscription(api, values)
        assert await coord.async_refresh_clu_state("clu1")
        groups = api._groups.copy()
        stats["requests"].clear()
        values[keys[0]] = 999
        values[keys[31]] = 888
        assert await coord.async_refresh_clu_state("clu1", required_states=[states[0]])
        assert coord.get_value_for_component(states[0]) == 999
        assert coord.get_value_for_component(states[31]) == 31
        assert [request.subscription_id for request in stats["requests"]] == [
            groups[0].subscription_id
        ]
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_ha_stop_cancels_loops_closes_control_and_listener_and_is_idempotent(tmp_path):
    async def run():
        from test_clu_protocol_lifecycle import socket_factory

        hass, _, coord, api = await fixture(tmp_path)
        coord.register_component_state(GrentonVariableValueObject("clu1", "", "value"))
        sockets = []
        with socket_factory(api, sockets):
            await coord.async_setup()
            tasks = [coord._ping_task, coord._register_task]
            assert len(sockets) == 2
            hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
            await hass.async_block_till_done()
            assert all(task.done() for task in tasks)
            assert coord._apis == {} and not api._groups
            assert api.transport is api.protocol is None
            assert api.report_transport is api.report_protocol is None
            assert api._closed and api.on_subscription_report is None
            assert all(socket.close_calls == 1 for socket in sockets)
            await coord.async_shutdown()
            assert all(socket.close_calls == 1 for socket in sockets)
            assert (
                await api.register_component_states(
                    [GrentonCluStateVariableKey("after_stop")]
                )
                is None
            )
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_shutdown_or_cancellation_during_registration_cannot_leak_shared_sockets(
    tmp_path, cancel
):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        state = GrentonCluStateVariableKey("a")
        stats = synthetic_subscription(api, {state: 1})
        control, listener = api.transport, api.report_transport
        original = api.protocol.send_request.side_effect
        started, release = asyncio.Event(), asyncio.Event()

        async def read(request):
            if isinstance(request, GrentonCluApiClientRegisterRequest):
                started.set()
                await release.wait()
            return await original(request)

        api.protocol.send_request.side_effect = read
        task = asyncio.create_task(api.register_component_states([state]))
        await started.wait()
        assert api._groups[0].registered
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await api.disconnect()
        else:
            await api.disconnect()
            release.set()
            assert await task is None
        assert not api._groups
        assert api.transport is api.report_transport is None
        control.close.assert_called_once()
        listener.close.assert_called_once()
        assert any(
            isinstance(request, GrentonCluApiClientDestroyRequest)
            for request in stats["requests"]
        )
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_socket_created_after_disconnect_is_immediately_closed(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        transport = Mock()
        transport.is_closing.return_value = False
        started, release = asyncio.Event(), asyncio.Event()

        async def create(factory, **kwargs):
            started.set()
            await release.wait()
            return transport, factory()

        with patch.object(
            asyncio.get_running_loop(), "create_datagram_endpoint", side_effect=create
        ):
            task = asyncio.create_task(api.connect())
            await started.wait()
            await api.disconnect()
            release.set()
            assert not await task
        transport.close.assert_called_once()
        assert api.transport is None and api.protocol is None
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_closing_protocol_fails_pending_requests_without_waiting_for_timeout(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        protocol = GrentonCluApiProtocol(api)
        api.cipher = SimpleNamespace(encrypt=lambda value: value)
        sent = asyncio.Event()
        protocol.transport = SimpleNamespace(sendto=lambda *args: sent.set())
        task = asyncio.create_task(
            protocol.send_request(GrentonCluApiPingRequest("00000001"))
        )
        await sent.wait()
        protocol.connection_lost(None)
        with pytest.raises(ConnectionError):
            await task
        assert protocol.transport is None and protocol._pending == {}
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("unloaded", [False, True])
def test_unload_failure_keeps_the_existing_connection_alive(tmp_path, unloaded):
    async def run():
        hass, entry, coord, _ = await fixture(tmp_path)
        entry.runtime_data = SimpleNamespace(coordinator=coord)
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=unloaded)
        coord.async_shutdown = AsyncMock()
        assert await async_unload_entry(hass, entry) is unloaded
        assert coord.async_shutdown.await_count == int(unloaded)
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["coordinator", "platform"])
def test_setup_failure_closes_the_coordinator(tmp_path, stage):
    async def run():
        hass, entry, coord, _ = await fixture(tmp_path)
        interface = {
            "id": "test",
            "version": 1,
            "name": "Home",
            "icon": "home",
            "theme": "GRENTON",
            "encryption": {"key": "00" * 16, "iv": "00" * 16},
            "clus": [],
            "pages": [],
            "pushNotifications": [],
        }
        entry = make_entry(interface=interface)
        coord.config_entry = entry
        coord.async_setup = AsyncMock(
            side_effect=HomeAssistantError("setup failed")
            if stage == "coordinator"
            else None
        )
        coord.async_shutdown = AsyncMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock(
            side_effect=HomeAssistantError("setup failed")
            if stage == "platform"
            else None
        )
        with (
            patch(
                "custom_components.homeassistant_grenton.GrentonCoordinator",
                return_value=coord,
            ),
            pytest.raises(HomeAssistantError, match="setup failed"),
        ):
            await async_setup_entry(hass, entry)
        coord.async_shutdown.assert_awaited_once()
        await hass.async_stop()

    asyncio.run(run())


def test_startup_retries_only_failed_subscription_groups(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        states = [GrentonVariableValueObject("clu1", "", str(i)) for i in range(61)]
        for state in states:
            coord.register_component_state(state)
        keys = coord.state.clus["clu1"].get_subscription_order()
        stats = synthetic_subscription(api, dict(zip(keys, range(61))))
        original = api.protocol.send_request.side_effect
        failed = False

        async def fail_once(request):
            nonlocal failed
            if (
                isinstance(request, GrentonCluApiClientRegisterRequest)
                and keys[31] in request.keys
                and not failed
            ):
                failed = True
                stats["requests"].append(request)
                return None
            return await original(request)

        api.protocol.send_request.side_effect = fail_once
        api.connect = AsyncMock(return_value=True)
        api.ping = AsyncMock(return_value=True)
        await coord.async_setup()
        counts = [
            sum(
                isinstance(request, GrentonCluApiClientRegisterRequest)
                and request.subscription_id == group.subscription_id
                for request in stats["requests"]
            )
            for group in api._groups
        ]
        assert counts == [1, 2, 1]
        assert coord.get_value_for_component(states[31]) == 31
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())
