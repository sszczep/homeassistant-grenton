"""Slow reads avoid realtime registrations and share the existing control socket."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from probatio import Invalid
from test_clu_lifecycle import fixture
from test_clu_scripts import make_entry, make_hass
from test_clu_state import coordinator, make_clu
from test_clu_variables import configure_manager, set_options
from test_integration_configuration import fields
from test_scene_configuration import ui_fields
from test_thermostat_v2 import widget as thermostat_widget
from test_value_v2_configuration import double_widget, widget

from custom_components.homeassistant_grenton.domain.api.clu import (
    GrentonCluApiProtocol,
)
from custom_components.homeassistant_grenton.domain.api.clu_messages import (
    GrentonCluApiFetchValuesRequest,
    GrentonCluApiGetValueRequest,
)
from custom_components.homeassistant_grenton.domain.entities.clu_state import (
    clu_entities,
)
from custom_components.homeassistant_grenton.domain.state_object import (
    GrentonVariableValueObject,
)
from custom_components.homeassistant_grenton.integration_config import RuntimeData
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper
from custom_components.homeassistant_grenton.read_policy import (
    slow_read_interval,
    validate_slow_read_interval,
)
from custom_components.homeassistant_grenton.state import (
    MISSING_STATE,
    GrentonCluStateVariableKey,
)


@pytest.mark.parametrize(
    "value", [None, True, False, 0, -1, 60.5, 86401, "60", float("nan"), float("inf")]
)
def test_invalid_intervals_cannot_create_a_busy_loop(value):
    with pytest.raises(Invalid):
        validate_slow_read_interval(value)
    assert slow_read_interval({"slow_read_interval": value}, "clu1") == 60


@pytest.mark.parametrize("value", [1, 5, 60.0, 120, 86400])
def test_valid_intervals(value):
    assert validate_slow_read_interval(value) == value
    assert isinstance(validate_slow_read_interval(value), int)
    assert slow_read_interval({}, "clu1") == 60


def test_per_clu_intervals_inherit_legacy_global_without_losing_overrides():
    options = {
        "slow_read_interval": 90,
        "clu_read_settings": {"clu2": {"slow_read_interval": 5}},
    }
    assert slow_read_interval(options, "clu1") == 90
    assert slow_read_interval(options, "clu2") == 5
    assert (
        slow_read_interval(
            {"clu_read_settings": {"clu2": {"slow_read_interval": 0}}}, "clu2"
        )
        == 60
    )


@pytest.mark.parametrize("widget_factory", [widget, double_widget])
@pytest.mark.parametrize("saved_mode", [None, "realtime", "slow"])
def test_existing_temperature_values_switch_to_slow_on_load(
    tmp_path, widget_factory, saved_mode
):
    async def run():
        entry = make_entry()
        config = {"device_class": "temperature", "unit_of_measurement": "°C"}
        if saved_mode is not None:
            config["read_mode"] = saved_mode
        set_options(entry, {"entities": {"front_door_0": config}})
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu2")])
        entities = DeviceMapper.to_domain(widget_factory(), coord).entities
        value = entities[0]
        assert coord.state_read_mode(value.state_object) == "slow"
        assert value.extra_state_attributes["read_mode"] == "slow"
        form = value._get_schema_instance()._build_type(config, {})
        assert ui_fields({"data_schema": form.schema})["read_mode"]["default"] == "slow"
        if len(entities) == 2:
            assert coord.state_read_mode(entities[1].state_object) == "realtime"
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_http_gate_polls_small_bindings_and_active_schedule_without_subscriptions(
    tmp_path,
):
    async def run():
        entry = make_entry()
        set_options(entry, {"clu_read_settings": {"clu1": {"slow_read_interval": 5}}})
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu1", prefix="521")
        coord = coordinator(hass, entry, [clu])
        thermostat = DeviceMapper.to_domain(thermostat_widget(), coord).entities[0]
        clu_entities(coord, clu)
        api = coord._apis["clu1"]
        api.connect = AsyncMock(return_value=True)
        api.ping = AsyncMock(return_value=True)
        api._ensure_report_listener = AsyncMock()
        requests = []

        async def read(request):
            requests.append(request)
            if isinstance(request, GrentonCluApiGetValueRequest):
                assert request.key.name == "9"
                return f"resp:192.0.2.1:{request.msg_id}:{'Y0' * 672}+00:30"
            payload = ",".join(
                '"Y0' + "Y0" * 671 + '+00:30"'
                if key.name == "9"
                else "1"
                if key.name == "6"
                else "2"
                if key.name == "8"
                else "30"
                for key in request.keys
            )
            return f"resp:192.0.2.1:{request.msg_id}:values:{{{payload}}}"

        api.protocol = SimpleNamespace(send_request=AsyncMock(side_effect=read))
        await coord.async_setup()
        assert not coord._realtime_keys[clu.id]
        assert (
            set(coord.state.clus[clu.id].get_subscription_order())
            == coord._slow_keys[clu.id]
        )
        assert coord._slow_read_intervals[clu.id] == 5
        assert len(requests) == 2  # Ordinary values, then one isolated active schedule.
        assert isinstance(requests[0], GrentonCluApiFetchValuesRequest)
        assert requests[0].payload.startswith("SYSTEM:fetchValues({")
        assert isinstance(requests[1], GrentonCluApiGetValueRequest)
        assert requests[1].payload == "THERMOSTAT1:get(9)"
        assert [key.name for key in requests[-1].keys] == ["9"]
        assert thermostat.decoded_schedule is not None
        api._ensure_report_listener.assert_not_awaited()
        assert not api._groups
        await coord._send_register(clu.id)
        assert len(requests) == 2  # No 45-second registration for this CLU.
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["target", "mode"])
def test_thermostat_writes_read_back_polled_target_immediately(tmp_path, operation):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        thermostat = DeviceMapper.to_domain(thermostat_widget(), coord).entities[0]
        values = {
            "6": 1,
            "7": 0,
            "8": 0,
            "9": "Y0" * 672 + "+00:30",
            "10": 0,
            "11": 30,
            "12": 20,
            "13": 0,
            "14": 21,
        }
        api.register_component_states = AsyncMock(
            side_effect=lambda keys, **kwargs: [values[key.name] for key in keys]
        )
        api.poll_component_states = AsyncMock(
            side_effect=lambda keys: [values[key.name] for key in keys]
        )

        async def write(action, **kwargs):
            if action.index == "3":
                values["12"] = float(action.value)
            if action.index == "8":
                values["12"] = 23
            return True

        api.execute_action = AsyncMock(side_effect=write)
        assert await coord.async_refresh_clu_state("clu1")
        api.poll_component_states.reset_mock()
        api.register_component_states.reset_mock()
        if operation == "target":
            await thermostat.async_set_temperature(temperature=22.5)
            assert thermostat.target_temperature == 22.5
        else:
            await thermostat.async_set_hvac_mode("auto")
            assert thermostat.target_temperature == 23
        api.poll_component_states.assert_awaited_once_with(
            [coord._state_key(thermostat.states["targetTemperature"])]
        )
        api.register_component_states.assert_not_awaited()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_poll_batches_use_existing_socket_and_distinct_request_ids(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        keys = [GrentonCluStateVariableKey(str(i)) for i in range(65)]
        requests = []

        async def read(request):
            requests.append(request)
            values = ",".join(key.name for key in request.keys)
            return f"resp:192.0.2.1:{request.msg_id}:values:{{{values}}}"

        api.protocol = SimpleNamespace(send_request=AsyncMock(side_effect=read))
        api._ensure_report_listener = AsyncMock()
        assert await api.poll_component_states(keys) == list(range(65))
        assert await api.poll_component_states(keys[:1]) == [0]
        assert [len(request.keys) for request in requests] == [30, 30, 5, 1]
        assert all(
            isinstance(request, GrentonCluApiFetchValuesRequest) for request in requests
        )
        assert len({request.msg_id for request in requests}) == 4
        assert not api._groups
        api._ensure_report_listener.assert_not_awaited()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_failed_poll_batch_does_not_shift_values_or_confuse_nil(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        keys = [GrentonCluStateVariableKey(str(i)) for i in range(31)]
        api.protocol = SimpleNamespace(
            send_request=AsyncMock(
                side_effect=[
                    None,
                    "resp:192.0.2.1:12345678:values:{nil}",
                    "resp:192.0.2.1:12345678:values:{1,2}",
                    ConnectionError("closed"),
                ]
            )
        )
        assert await api.poll_component_states(keys) == [MISSING_STATE] * 30 + [None]
        assert await api.poll_component_states(keys[:1]) == [MISSING_STATE]
        assert await api.poll_component_states(keys[:1]) == [MISSING_STATE]
        await coord.async_shutdown()
        assert await api.poll_component_states(keys[:1]) == [MISSING_STATE]
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("realtime_first", [False, True])
def test_realtime_consumer_wins_for_shared_bindings(tmp_path, realtime_first):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        shared = GrentonVariableValueObject("clu1", "", "shared")
        slow = GrentonVariableValueObject("clu1", "", "slow")
        modes = ["realtime", "slow"] if realtime_first else ["slow", "realtime"]
        for mode in modes:
            coord.register_component_state(shared, read_mode=mode)
        coord.register_component_state(slow, read_mode="slow")
        api.register_component_states = AsyncMock(return_value=[21])
        api.poll_component_states = AsyncMock(return_value=[19])
        assert await coord.async_refresh_clu_state("clu1")
        api.register_component_states.assert_awaited_once_with(
            [coord._state_key(shared)]
        )
        api.poll_component_states.assert_awaited_once_with([coord._state_key(slow)])
        assert coord.state_read_mode(shared) == "realtime"
        assert coord.last_polled(shared) is None
        assert coord.get_value_for_component(shared) == 21
        assert coord.get_value_for_component(slow) == 19
        # The 45-second registration path never includes slow-only keys.
        api.poll_component_states.reset_mock()
        await coord._send_register("clu1")
        api.poll_component_states.assert_not_awaited()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_temperature_shared_with_thermostat_uses_one_polled_binding(tmp_path):
    async def run():
        hass, entry, coord, api = await fixture(tmp_path)
        set_options(entry, {"entities": {"front_door_0": {"read_mode": "slow"}}})
        dto = widget("FLOAT")
        dto.object.value.cluId = "clu1"
        dto.object.value.objectName = "THERMOSTAT1"
        dto.object.value.index = "14"
        value = DeviceMapper.to_domain(dto, coord).entities[0]
        thermostat = DeviceMapper.to_domain(thermostat_widget(), coord).entities[0]
        key = coord._state_key(value.state_object)
        assert key not in coord._realtime_keys["clu1"]
        assert key in coord._slow_keys["clu1"]
        api.poll_component_states = AsyncMock(
            side_effect=lambda keys: [21.5 for key in keys]
        )
        await coord._send_slow_poll("clu1")
        assert value.native_value == thermostat.current_temperature == 21.5
        assert value.available
        assert value.extra_state_attributes["effective_read_mode"] == "slow"
        assert value.extra_state_attributes["last_polled"]
        polled = api.poll_component_states.await_args.args[0]
        assert polled.count(key) == 1
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_slow_values_start_unknown_retain_failed_reads_then_expire(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        states = [GrentonVariableValueObject("clu1", "", str(i)) for i in range(2)]
        for state in states:
            coord.register_component_state(state, read_mode="slow")
        assert not coord.is_state_fresh(states[0])
        assert coord.get_value_for_component(states[0]) is None
        api.poll_component_states = AsyncMock(
            side_effect=[
                [20, 22],
                [MISSING_STATE, None],
                [MISSING_STATE, MISSING_STATE],
                [21, 23],
            ]
        )
        with patch(
            "custom_components.homeassistant_grenton.coordinator.monotonic",
            return_value=100,
        ):
            await coord._send_slow_poll("clu1")
            stamp = coord.last_polled(states[0])
            assert stamp is not None and stamp.endswith("+00:00")
            assert coord.get_value_for_component(states[0]) == 20
        with patch(
            "custom_components.homeassistant_grenton.coordinator.monotonic",
            return_value=160,
        ):
            await coord._send_slow_poll("clu1")
            assert coord.is_state_fresh(states[0])
            assert coord.get_value_for_component(states[0]) == 20
            assert coord.last_polled(states[0]) == stamp
            assert coord.is_state_fresh(states[1])  # Actual nil is a successful read.
            assert coord.get_value_for_component(states[1]) is None
        with patch(
            "custom_components.homeassistant_grenton.coordinator.monotonic",
            return_value=220,
        ):
            await coord._send_slow_poll("clu1")
            assert not coord.is_state_fresh(states[0])
            assert coord.get_value_for_component(states[0]) is None
            assert coord.is_state_fresh(states[1])
            assert coord.state.get_value_for_component(states[0]) == 20
            await coord._send_slow_poll("clu1")
            assert coord.is_state_fresh(states[0])
            assert coord.get_value_for_component(states[0]) == 21
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_startup_reads_all_clus_once_and_shutdown_cancels_slow_tasks(tmp_path):
    async def run():
        entry = make_entry()
        set_options(entry, {"slow_read_interval": 120})
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu1"), make_clu("clu2")])
        for clu_id, api in coord._apis.items():
            state = GrentonVariableValueObject(clu_id, "", "temp")
            coord.register_component_state(state, read_mode="slow")
            api.connect = AsyncMock(return_value=True)
            api.ping = AsyncMock(return_value=True)
            api.register_component_states = AsyncMock()
            api.poll_component_states = AsyncMock(return_value=[21])
        await coord.async_setup()
        for api in coord._apis.values():
            api.register_component_states.assert_not_awaited()
            api.poll_component_states.assert_awaited_once()
        assert coord._slow_read_intervals["clu1"] == 120
        tasks = list(coord._slow_tasks.values())
        assert len(tasks) == 2
        await coord.async_shutdown()
        assert all(task.done() for task in tasks)
        assert not coord._slow_tasks
        await hass.async_stop()

    asyncio.run(run())


def test_loop_waits_for_clu_interval_without_fast_failure_retries(tmp_path):
    async def run():
        hass, _, coord, _ = await fixture(tmp_path)
        coord._slow_read_intervals["clu1"] = 120
        clock, waits = 0, []

        async def read(clu_id):
            nonlocal clock
            clock += 5
            raise RuntimeError("temporary failure")

        async def sleep(delay):
            nonlocal clock
            waits.append(delay)
            clock += delay
            if len(waits) == 2:
                raise asyncio.CancelledError

        coord._send_slow_poll = AsyncMock(side_effect=read)
        with (
            patch(
                "custom_components.homeassistant_grenton.coordinator.monotonic",
                side_effect=lambda: clock,
            ),
            patch("asyncio.sleep", side_effect=sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                await coord._slow_poll_loop("clu1")
            assert waits == [120, 115]
        coord._send_slow_poll.assert_awaited_once_with("clu1")
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_clu_flow_preserves_options_and_changes_only_selected_clu_timer(tmp_path):
    async def run():
        entry = make_entry(
            interface={
                "clus": [{"id": "clu1", "name": "Main"}, {"id": "clu2", "name": "Gate"}]
            }
        )
        original = {
            "entities": {"sensor_0": {"read_mode": "slow"}},
            "clu_variables": {"clu1": {}},
            "clu_read_settings": {"clu2": {"slow_read_interval": 5, "keep": True}},
        }
        set_options(entry, original)
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(
            hass, entry, [make_clu("clu1"), make_clu("clu2", prefix="521")]
        )
        for clu_id, api in coord._apis.items():
            coord.register_component_state(
                GrentonVariableValueObject(clu_id, "", "temp"), read_mode="slow"
            )
            api.connect = AsyncMock()
            api.disconnect = AsyncMock()
            api.register_component_states = AsyncMock()
        entry.runtime_data = RuntimeData(coord, [])
        coord._start_slow_tasks()
        old_tasks = coord._slow_tasks.copy()
        manager = configure_manager(hass, entry)
        menu = await manager.async_init(entry.entry_id)
        assert menu["type"] == "menu"
        assert menu["menu_options"] == [
            "clu_read_settings", "entity_list", "add_object", "gate_settings"
        ]
        form = await manager.async_configure(
            menu["flow_id"], {"next_step_id": "clu_read_settings"}
        )
        assert {
            row["value"]
            for row in fields(form)["clu_id"]["selector"]["select"]["options"]
        } == {"clu1", "clu2"}
        form = await manager.async_configure(form["flow_id"], {"clu_id": "clu1"})
        assert form["step_id"] == "clu_configuration"
        form = await manager.async_configure(
            form["flow_id"], {"next_step_id": "clu_read_interval"}
        )
        assert fields(form)["slow_read_interval"]["default"] == 60
        invalid = await manager.async_configure(
            form["flow_id"], {"slow_read_interval": 60.5}
        )
        assert invalid["errors"] == {"slow_read_interval": "invalid_configuration"}
        assert dict(entry.options) == original
        assert coord._slow_read_intervals == {"clu1": 60, "clu2": 5}
        result = await manager.async_configure(
            form["flow_id"], {"slow_read_interval": 120}
        )
        assert result["type"] == "create_entry"
        assert dict(entry.options) == {
            **original,
            "clu_read_settings": {
                **original["clu_read_settings"],
                "clu1": {"slow_read_interval": 120, "subscription_id": 1},
            },
        }
        assert coord._slow_read_intervals == {"clu1": 120, "clu2": 5}
        assert old_tasks["clu1"].done()
        assert coord._slow_tasks["clu2"] is old_tasks["clu2"]
        assert not old_tasks["clu2"].done()
        for api in coord._apis.values():
            api.connect.assert_not_awaited()
            api.disconnect.assert_not_awaited()
            api.register_component_states.assert_not_awaited()
        hass.config_entries.async_schedule_reload.assert_not_called()
        # Reopen the other CLU: its own faster interval is retained.
        reopened = await manager.async_init(entry.entry_id)
        reopened = await manager.async_configure(
            reopened["flow_id"], {"next_step_id": "clu_read_settings"}
        )
        reopened = await manager.async_configure(
            reopened["flow_id"], {"clu_id": "clu2"}
        )
        reopened = await manager.async_configure(
            reopened["flow_id"], {"next_step_id": "clu_read_interval"}
        )
        assert fields(reopened)["slow_read_interval"]["default"] == 5
        manager.async_abort(reopened["flow_id"])
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("widget_factory", [widget, double_widget])
@pytest.mark.parametrize("entity_type", ["sensor", "binary_sensor"])
def test_value_flow_persists_read_mode_and_double_channels_remain_independent(
    tmp_path, widget_factory, entity_type
):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu2")])
        device = DeviceMapper.to_domain(widget_factory(), coord)
        entity = device.entities[0]
        entity.entity_id = "sensor.front_door"
        entry.runtime_data = RuntimeData(coord, [device])
        er.async_get(hass).async_get_or_create(
            "sensor",
            "grenton",
            entity.unique_id,
            config_entry=entry,
            suggested_object_id="front_door",
        )
        manager = configure_manager(hass, entry)
        form = await manager.async_init(entry.entry_id)
        form = await manager.async_configure(
            form["flow_id"], {"next_step_id": "entity_list"}
        )
        form = await manager.async_configure(
            form["flow_id"], {"entity": entity.entity_id}
        )
        assert fields(form)["read_mode"]["default"] == "realtime"
        form = await manager.async_configure(
            form["flow_id"], {"entity_type": entity_type, "read_mode": "slow"}
        )
        inputs = {"device_class": "none"}
        if entity_type == "binary_sensor":
            inputs["invert_state"] = False
        result = await manager.async_configure(form["flow_id"], inputs)
        if entity_type == "sensor":
            assert result["step_id"] == "configure_sensor_unit"
            result = await manager.async_configure(result["flow_id"], {})
        assert result["type"] == "create_entry"
        assert entry.options["entities"][entity.unique_id]["read_mode"] == "slow"
        hass.config_entries.async_schedule_reload.assert_called_once_with(
            entry.entry_id
        )
        # Reloading reconstructs the selected channel with slow registration.
        restored = coordinator(hass, entry, [make_clu("clu2")])
        entities = DeviceMapper.to_domain(widget_factory(), restored).entities
        assert restored.state_read_mode(entities[0].state_object) == "slow"
        assert not entities[0].available
        assert entities[0].extra_state_attributes["last_polled"] is None
        if len(entities) == 2:
            assert restored.state_read_mode(entities[1].state_object) == "realtime"
        api = restored._apis["clu2"]
        api.poll_component_states = AsyncMock(return_value=[21])
        await restored._send_slow_poll("clu2")
        assert entities[0].available
        assert entities[0].extra_state_attributes["effective_read_mode"] == "slow"
        assert entities[0].extra_state_attributes["last_polled"]
        await coord.async_shutdown()
        await restored.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_changing_interval_cancels_inflight_read_and_clears_pending_request(tmp_path):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        state = GrentonVariableValueObject("clu1", "", "temp")
        coord.register_component_state(state, read_mode="slow")
        protocol = GrentonCluApiProtocol(api)
        protocol.transport = Mock()
        api.protocol = protocol
        task = asyncio.create_task(coord._send_slow_poll("clu1"))
        coord._slow_tasks["clu1"] = task
        # Wait until the simulated datagram has been sent and a reply is pending.
        for _ in range(10):
            await asyncio.sleep(0)
            if protocol._pending:
                break
        assert protocol._pending
        await coord.async_set_slow_read_interval("clu1", 120)
        assert task.cancelled()
        assert not protocol._pending
        assert len(coord._slow_tasks) == 1
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())
