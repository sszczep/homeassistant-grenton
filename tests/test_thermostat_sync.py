"""Startup reads, large UDP values and races with pushed changes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_clu_scripts import make_entry, make_hass
from test_clu_state import coordinator, make_clu
from test_thermostat_v2 import widget

from custom_components.homeassistant_grenton.domain.api.clu import (
    GrentonCluApiProtocol,
)
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper
from custom_components.homeassistant_grenton.state import (
    MISSING_STATE,
    GrentonCluStateAttributeKey,
    GrentonCluStateVariableKey,
)


def test_schedule_poll_is_isolated_and_shared_report_socket_is_reused(
    tmp_path,
):
    async def run():
        from test_clu_lifecycle import synthetic_subscription

        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu1")])
        entity = DeviceMapper.to_domain(widget(), coord).entities[0]
        api = coord._apis["clu1"]
        keys = [
            key
            for key in coord.state.clus["clu1"].get_subscription_order()
            if key in coord._realtime_keys["clu1"]
        ]
        schedule_key = GrentonCluStateAttributeKey("THERMOSTAT1", "9")
        assert api.large_value_keys == {schedule_key} and schedule_key not in keys
        week = "Y0" * 672 + "+00:30"
        synthetic_subscription(
            api,
            {
                key: 1 if key.name == "6" else 2 if key.name == "8" else 30
                for key in keys
            },
        )
        api.poll_component_states = AsyncMock(
            side_effect=lambda selected: [
                week if key == schedule_key else 30 for key in selected
            ]
        )
        values = await api.register_component_states(keys)
        groups, listener = api._groups.copy(), api.report_transport
        assert all(schedule_key not in group.keys for group in groups)
        await coord._process_report("clu1", keys, values)
        await coord._send_slow_poll("clu1")
        assert entity.decoded_schedule is not None
        assert api.poll_component_states.await_args.args[0] == [schedule_key]
        assert await api.register_component_states(keys) == values
        assert api._groups == groups and api.report_transport is listener
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize(
    "wire",
    [
        None,
        "resp:192.0.2.1:abcd:clientReport:1:{1}",
        "resp:192.0.2.1:abcd:clientReport:1:{1,2,3}",
        "resp:192.0.2.1:abcd:error",
    ],
)
def test_bad_chunk_preserves_alignment_of_later_values(tmp_path, wire):
    async def run():
        from test_clu_lifecycle import synthetic_subscription

        from custom_components.homeassistant_grenton.domain.api.clu_messages import (
            GrentonCluApiClientRegisterRequest,
        )

        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu1")])
        api = coord._apis["clu1"]
        keys = [GrentonCluStateVariableKey(str(index)) for index in range(31)]
        synthetic_subscription(api, {key: 999 for key in keys})
        original = api.protocol.send_request.side_effect

        async def read(request):
            if (
                isinstance(request, GrentonCluApiClientRegisterRequest)
                and len(request.keys) == 30
            ):
                return wire
            return await original(request)

        api.protocol.send_request.side_effect = read
        assert await api.register_component_states(keys) == [MISSING_STATE] * 30 + [999]
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_newer_push_wins_over_registration_snapshot_and_actual_nil_clears_state(
    tmp_path,
):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu1")])
        entity = DeviceMapper.to_domain(widget(), coord).entities[0]
        keys = coord.state.clus["clu1"].get_subscription_order()
        values = {
            "6": 1,
            "7": 0,
            "8": 2,
            "9": "Y0" * 672 + "+00:30",
            "10": 0,
            "11": 30,
            "12": 20,
            "13": 0,
            "14": 21,
        }

        async def initial_read(_keys):
            await coord._process_report("clu1", [keys[0]], [0])
            return [values[key.name] for key in _keys]

        coord._apis["clu1"] = SimpleNamespace(
            state_read_batches=coord._apis["clu1"].state_read_batches,
            register_component_states=AsyncMock(side_effect=initial_read),
            poll_component_states=AsyncMock(
                side_effect=lambda keys: [values[key.name] for key in keys]
            ),
        )
        assert await coord.async_refresh_clu_state("clu1")
        assert entity.hvac_mode == "off"  # Old snapshot says on; newer push says off.
        assert entity.decoded_schedule is None  # Off pauses the large schedule read.
        schedule_state = entity.states["scheduleData"]
        assert await coord.async_refresh_clu_state(
            "clu1", required_states=[schedule_state]
        )
        assert entity.schedule_status == "ready"
        values["9"], week = None, values["9"]
        assert await coord.async_refresh_clu_state(
            "clu1", required_states=[schedule_state]
        )
        assert entity.decoded_schedule is None
        assert coord.get_value_for_component(entity.states["scheduleData"]) is None
        # Failed network reads retain the previous valid value; actual nil does not.
        values["9"] = week
        assert await coord.async_refresh_clu_state(
            "clu1", required_states=[schedule_state]
        )
        coord._apis["clu1"].register_component_states.side_effect = None
        coord._apis["clu1"].register_component_states.return_value = [
            MISSING_STATE
        ] * len(keys)
        assert not await coord.async_refresh_clu_state("clu1")
        assert entity.schedule_status == "ready"
        await hass.async_stop()

    asyncio.run(run())


def test_startup_retries_small_reads_then_loads_active_auto_schedule(tmp_path):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu1")])
        entity = DeviceMapper.to_domain(widget(), coord).entities[0]
        keys = [
            key
            for key in coord.state.clus["clu1"].get_subscription_order()
            if key in coord._realtime_keys["clu1"]
        ]
        values = {
            "6": 1,
            "7": 1,
            "8": 2,
            "9": "SN" * 672 + "+00:2$",
            "10": 20,
            "11": 33,
            "12": 20,
            "13": 1,
            "14": 21,
        }
        api = SimpleNamespace(
            state_read_batches=coord._apis["clu1"].state_read_batches,
            connect=AsyncMock(return_value=True),
            ping=AsyncMock(return_value=True),
            disconnect=AsyncMock(),
            execute_action=AsyncMock(),
            poll_component_states=AsyncMock(
                side_effect=lambda keys: [values[key.name] for key in keys]
            ),
            register_component_states=AsyncMock(
                side_effect=[
                    [MISSING_STATE] * len(keys),
                    [values[key.name] for key in keys],
                ]
            ),
        )
        coord._apis["clu1"] = api
        await coord.async_setup()
        assert api.register_component_states.await_count == 2
        assert (
            sum(
                key.name == "9"
                for call in api.poll_component_states.await_args_list
                for key in call.args[0]
            )
            == 1
        )
        assert entity.schedule_status == "ready"
        assert set(entity.decoded_schedule.temperatures) == {20}
        assert entity.hvac_mode == "auto" and entity.control_direction_name == "cooling"
        api.execute_action.assert_not_called()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_incomplete_unsolicited_reports_are_ignored(tmp_path):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu1")])
        protocol = GrentonCluApiProtocol(coord._apis["clu1"])
        protocol.subscription_keys = [
            GrentonCluStateVariableKey("a"),
            GrentonCluStateVariableKey("b"),
        ]
        protocol.subscription_callback = AsyncMock()
        protocol._process_response("resp:192.0.2.1:00000000:clientReport:0:{1}")
        await asyncio.sleep(0)
        protocol.subscription_callback.assert_not_awaited()
        protocol._process_response("resp:192.0.2.1:00000000:clientReport:0:{1,2}")
        await asyncio.sleep(0)
        protocol.subscription_callback.assert_awaited_once_with([1, 2])
        await hass.async_stop()

    asyncio.run(run())


def test_packets_from_separate_sockets_share_pacing_and_cancellation_cleans_pending(
    tmp_path,
):
    from unittest.mock import Mock, patch

    from custom_components.homeassistant_grenton.domain.api.clu_messages import (
        GrentonCluApiPingRequest,
    )

    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu1")])
        api = coord._apis["clu1"]
        api.cipher = SimpleNamespace(encrypt=lambda value: value)
        protocols = [GrentonCluApiProtocol(api) for _ in range(2)]
        entered, release = asyncio.Event(), asyncio.Event()

        async def spacing(delay):
            assert 0 < delay <= 0.02
            entered.set()
            await release.wait()

        for protocol in protocols:
            protocol.transport = SimpleNamespace(sendto=Mock())
        with patch(
            "custom_components.homeassistant_grenton.domain.api.clu.asyncio.sleep",
            side_effect=spacing,
        ):
            first = asyncio.create_task(
                protocols[0].send_request(GrentonCluApiPingRequest("00000001"))
            )
            await asyncio.get_running_loop().run_in_executor(None, lambda: None)
            second = asyncio.create_task(
                protocols[1].send_request(GrentonCluApiPingRequest("00000002"))
            )
            await entered.wait()
            # Both requests are queued, but the spacing gate allows only one send.
            await asyncio.get_running_loop().run_in_executor(None, lambda: None)
            protocols[0].transport.sendto.assert_called_once()
            protocols[1].transport.sendto.assert_not_called()
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            release.set()
            await asyncio.get_running_loop().run_in_executor(None, lambda: None)
            protocols[1]._process_response("resp:192.0.2.1:00000002:pong")
            assert await second is not None
            assert protocols[0]._pending == protocols[1]._pending == {}
        await hass.async_stop()

    asyncio.run(run())


def test_timeout_diagnostics_identify_the_operation(tmp_path, caplog):
    from unittest.mock import Mock

    from custom_components.homeassistant_grenton.domain.api.clu_messages import (
        GrentonCluApiClientDestroyRequest,
        GrentonCluApiClientRegisterRequest,
        GrentonCluApiFetchValuesRequest,
        GrentonCluApiPingRequest,
    )
    from custom_components.homeassistant_grenton.domain.api.clu_messages.base import (
        GrentonCluApiRequest,
    )

    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu1")])
        api = coord._apis["clu1"]
        api.cipher = SimpleNamespace(encrypt=lambda value: value)
        protocol = GrentonCluApiProtocol(api)
        protocol.transport = SimpleNamespace(sendto=Mock())
        protocol._response_timeout = 0
        for request in (
            GrentonCluApiPingRequest("00000001"),
            GrentonCluApiClientRegisterRequest(
                [GrentonCluStateVariableKey("a")], 0, "00000002"
            ),
            GrentonCluApiRequest('THERMOSTAT1:set(9,"data")', "00000003"),
            GrentonCluApiFetchValuesRequest(
                [GrentonCluStateVariableKey("a")], "00000004"
            ),
            GrentonCluApiClientDestroyRequest(1234, "00000005"),
        ):
            assert await protocol.send_request(request) is None
        assert "timeout during ping" in caplog.text
        assert "timeout during subscription registration (1 keys)" in caplog.text
        assert "timeout during subscription destruction" in caplog.text
        assert "timeout during action write" in caplog.text
        assert "timeout during slow read (1 keys)" in caplog.text
        assert protocol._pending == {}
        await hass.async_stop()

    asyncio.run(run())
