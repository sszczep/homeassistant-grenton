"""Schedule polling is per thermostat, conditional, isolated and optional."""

import asyncio
from time import monotonic
from unittest.mock import AsyncMock

import pytest
from test_clu_scripts import make_entry, make_hass
from test_clu_state import coordinator, make_clu
from test_clu_variables import set_options
from test_scene_configuration import make_flow, ui_fields
from test_thermostat_schedule import constant_week
from test_thermostat_v2 import widget

from custom_components.homeassistant_grenton.domain.state_object import (
    GrentonAttributeValueObject,
)
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper
from custom_components.homeassistant_grenton.state import MISSING_STATE


async def fixture(
    tmp_path,
    *,
    poll_only=False,
    power=1,
    mode=0,
    consumer_mode=None,
    consumer_first=False,
    schedule_polling_enabled=None,
):
    entry = make_entry()
    if schedule_polling_enabled is not None:
        set_options(
            entry,
            {
                "entities": {
                    "thermostat1_climate": {
                        "schedule_polling_enabled": schedule_polling_enabled,
                    }
                }
            },
        )
    hass = await make_hass(tmp_path, [entry])
    clu = make_clu("clu1", prefix="521" if poll_only else "221")
    coord = coordinator(hass, entry, [clu])
    if consumer_mode and consumer_first:
        coord.register_component_state(
            GrentonAttributeValueObject(clu.id, "THERMOSTAT1", "9"),
            read_mode=consumer_mode,
        )
    entity = DeviceMapper.to_domain(widget(), coord).entities[0]
    if consumer_mode and not consumer_first:
        coord.register_component_state(
            entity.states["scheduleData"], read_mode=consumer_mode
        )
    values = {
        "6": power,
        "7": 0,
        "8": mode,
        "9": "Y0" * 672 + "+00:30",
        "10": 0,
        "11": 30,
        "12": 20,
        "13": 0,
        "14": 21,
    }
    api = coord._apis[clu.id]
    api.connect = AsyncMock(return_value=True)
    api.ping = AsyncMock(return_value=True)
    api.disconnect = AsyncMock()
    api.register_component_states = AsyncMock(
        side_effect=lambda keys, **kwargs: [values[key.name] for key in keys]
    )
    api.poll_component_states = AsyncMock(
        side_effect=lambda keys: [values[key.name] for key in keys]
    )

    async def write(action):
        values[action.index] = (
            action.value if action.index == "9" else float(action.value)
        )
        return True

    api.execute_action = AsyncMock(side_effect=write)
    return hass, coord, entity, api, values


def schedule_reads(api):
    return [
        call.args[0]
        for call in api.poll_component_states.await_args_list
        if any(key.name == "9" for key in call.args[0])
    ]


def add_thermostat(coord, widget_id):
    """Give another widget independent state on the same CLU."""
    data = widget().model_dump()
    data["id"] = widget_id.lower()
    for source in data["object"].values():
        if isinstance(source, dict):
            source["objectName"] = widget_id
    return DeviceMapper.to_domain(type(widget()).model_validate(data), coord).entities[
        0
    ]


@pytest.mark.parametrize("poll_only", [False, True])
def test_polling_toggle_applies_live_preserves_siblings_and_survives_reload(
    tmp_path, poll_only
):
    async def run():
        hass, coord, entity, api, _ = await fixture(
            tmp_path, poll_only=poll_only, mode=2
        )
        siblings = [
            add_thermostat(coord, name) for name in ("THERMOSTAT2", "THERMOSTAT3")
        ]
        try:
            await coord.async_setup()
            assert len(schedule_reads(api)) == 3
            api.poll_component_states.reset_mock()
            options = await entity.apply_configuration(
                {"cooling_enabled": False, "schedule_polling_enabled": False}
            )
            set_options(coord.config_entry, options)
            assert not entity.schedule_polling_enabled
            assert all(sibling.schedule_polling_enabled for sibling in siblings)
            assert (
                options["entities"][entity.unique_id]["schedule_polling_enabled"]
                is False
            )
            api.execute_action.assert_not_awaited()
            await coord._send_slow_poll("clu1")
            assert {keys[0].object_name for keys in schedule_reads(api)} == {
                "THERMOSTAT2",
                "THERMOSTAT3",
            }

            # A legacy caller changing only cooling must not undo this setting.
            options = await entity.apply_configuration({"cooling_enabled": False})
            set_options(coord.config_entry, options)
            assert not entity.schedule_polling_enabled
            draft = ui_fields(
                {
                    "data_schema": entity._get_schema_instance()
                    ._build(entity._config, {})
                    .schema
                }
            )["thermostat"]["description"]["suggested_value"]
            assert draft["schedule_polling_enabled"] is False
            restored = coordinator(
                hass,
                coord.config_entry,
                [make_clu("clu1", prefix="521" if poll_only else "221")],
            )
            reloaded = DeviceMapper.to_domain(widget(), restored).entities[0]
            assert not reloaded.schedule_polling_enabled
            await restored.async_shutdown()

            api.poll_component_states.reset_mock()
            await entity.apply_configuration(
                {"cooling_enabled": False, "schedule_polling_enabled": True}
            )
            assert entity.schedule_polling_enabled
            assert not schedule_reads(api)  # Enabling waits for the next poll.
            await coord._send_slow_poll("clu1")
            assert {keys[0].object_name for keys in schedule_reads(api)} == {
                "THERMOSTAT1",
                "THERMOSTAT2",
                "THERMOSTAT3",
            }
        finally:
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("poll_only", [False, True])
def test_polling_batch_rechecks_toggle_before_sending_each_schedule(
    tmp_path, poll_only
):
    async def run():
        hass, coord, first, api, _ = await fixture(
            tmp_path, poll_only=poll_only, mode=2
        )
        second = add_thermostat(coord, "THERMOSTAT2")
        try:
            await coord.async_setup()
            original = api.poll_component_states.side_effect

            async def read(keys):
                if keys == [coord._state_key(first.states["scheduleData"])]:
                    await second.apply_configuration(
                        {"cooling_enabled": False, "schedule_polling_enabled": False}
                    )
                return original(keys)

            api.poll_component_states.reset_mock()
            api.poll_component_states.side_effect = read
            await coord._send_slow_poll("clu1")
            assert [keys[0].object_name for keys in schedule_reads(api)] == [
                "THERMOSTAT1"
            ]
            assert not second.schedule_polling_enabled
            assert (
                second.decoded_schedule is not None
            )  # The last confirmed snapshot remains visible.
        finally:
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())


def test_active_schedule_expires_after_failures_but_paused_cache_remains_visible(
    tmp_path,
):
    async def run():
        hass, coord, entity, api, _ = await fixture(tmp_path, mode=2)
        try:
            await coord.async_setup()
            state = entity.states["scheduleData"]
            key = coord._state_key(state)
            _, stamp = coord._slow_success["clu1"][key]
            coord._slow_success["clu1"][key] = (monotonic() - 1000, stamp)
            assert not coord.is_state_fresh(state)
            assert entity.decoded_schedule is None
            await entity.apply_configuration(
                {"cooling_enabled": False, "schedule_polling_enabled": False}
            )
            assert coord.is_state_fresh(state)
            assert entity.decoded_schedule is not None
            api.poll_component_states.reset_mock()
            await coord._send_slow_poll("clu1")
            assert not schedule_reads(api)
        finally:
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("poll_only", [False, True])
@pytest.mark.parametrize("schedule_polling_enabled", [None, True, False])
@pytest.mark.parametrize(
    "power, mode",
    [
        (1, 2),
        (1, 0),
        (0, 2),
        (1, 1),
        (1, 3),
        (None, 2),
        (1, None),
    ],
)
def test_startup_reads_schedule_only_when_enabled_powered_and_auto(
    tmp_path, poll_only, power, mode, schedule_polling_enabled, caplog
):
    async def run():
        hass, coord, entity, api, _ = await fixture(
            tmp_path,
            poll_only=poll_only,
            power=power,
            mode=mode,
            schedule_polling_enabled=schedule_polling_enabled,
        )
        try:
            await coord.async_setup()
            key = coord._state_key(entity.states["scheduleData"])
            assert key not in coord._realtime_keys["clu1"]
            assert key in coord._slow_keys["clu1"]
            assert coord.state_read_mode(entity.states["scheduleData"]) == "slow"
            expected = (
                schedule_polling_enabled is not False and power == 1 and mode == 2
            )
            assert entity.schedule_polling_enabled == (
                schedule_polling_enabled is not False
            )
            assert bool(schedule_reads(api)) == expected
            assert all(keys == [key] for keys in schedule_reads(api))
            assert (entity.decoded_schedule is not None) == expected
            assert coord.is_state_fresh(entity.states["scheduleData"]) == expected
            entity._analyse_schedule()
            assert "Schedule unavailable" not in caplog.text
            assert all(
                key not in call.args[0]
                for call in api.register_component_states.await_args_list
            )
            assert not api._groups
        finally:
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("poll_only", [False, True])
@pytest.mark.parametrize("enabled", [True, False])
def test_mode_power_changes_and_generic_refreshes_follow_per_thermostat_setting(
    tmp_path, poll_only, enabled
):
    async def run():
        hass, coord, entity, api, values = await fixture(
            tmp_path, poll_only=poll_only, schedule_polling_enabled=enabled
        )
        try:
            await coord.async_setup()
            assert not schedule_reads(api)
            for mode, power in [
                (2, 1),
                (0, 1),
                (2, 0),
                (2, 1),
                (1, 1),
            ]:
                values.update({"8": mode, "6": power})
                if not poll_only:
                    await coord._process_report(
                        "clu1",
                        [
                            coord._state_key(entity.states[name])
                            for name in ("mode", "state")
                        ],
                        [mode, power],
                    )
                api.poll_component_states.reset_mock()
                await coord._send_slow_poll("clu1")
                assert bool(schedule_reads(api)) == (
                    enabled and mode == 2 and power == 1
                )
                api.poll_component_states.reset_mock()
                assert await coord.async_refresh_clu_state("clu1")
                assert bool(schedule_reads(api)) == (
                    enabled and mode == 2 and power == 1
                )
        finally:
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("poll_only", [False, True])
@pytest.mark.parametrize("consumer_mode", ["realtime", "slow"])
@pytest.mark.parametrize("consumer_first", [False, True])
@pytest.mark.parametrize("enabled", [True, False])
def test_shared_schedule_binding_retains_conditional_polling_in_either_registration_order(
    tmp_path, poll_only, consumer_mode, consumer_first, enabled
):
    async def run():
        hass, coord, entity, api, _ = await fixture(
            tmp_path,
            poll_only=poll_only,
            mode=2,
            consumer_mode=consumer_mode,
            consumer_first=consumer_first,
            schedule_polling_enabled=enabled,
        )
        try:
            await coord.async_setup()
            state = entity.states["scheduleData"]
            key = coord._state_key(state)
            assert coord.state_read_mode(state) == "slow"
            assert key in coord._slow_keys["clu1"]
            assert key not in coord._realtime_keys["clu1"]
            api.poll_component_states.reset_mock()
            await coord._send_slow_poll("clu1")
            assert await coord.async_refresh_clu_state("clu1")
            assert bool(schedule_reads(api)) == enabled
            assert all(
                key not in call.args[0]
                for call in api.register_component_states.await_args_list
            )
            api.poll_component_states.reset_mock()
            assert await coord.async_refresh_clu_state("clu1", required_states=[state])
            assert schedule_reads(api) == [[key]]
            assert entity.decoded_schedule is not None
        finally:
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("poll_only", [False, True])
@pytest.mark.parametrize("mode", [0, 2])
@pytest.mark.parametrize("enabled", [True, False])
def test_save_reads_schedule_before_and_after_write_and_preserves_polling_setting(
    tmp_path, poll_only, mode, enabled
):
    async def run():
        hass, coord, entity, api, values = await fixture(
            tmp_path,
            poll_only=poll_only,
            mode=mode,
            schedule_polling_enabled=enabled,
        )
        try:
            await coord.async_setup()
            api.poll_component_states.reset_mock()
            await entity.async_set_thermostat_schedule(constant_week(22))
            assert (
                len(schedule_reads(api)) == 2
            )  # Fresh encoding metadata, then one readback.
            assert set(entity.decoded_schedule.temperatures) == {22}
            assert values["8"] == mode and values["6"] == 1
            key = coord._state_key(entity.states["scheduleData"])
            assert all(keys == [key] for keys in schedule_reads(api))
            api.execute_action.assert_awaited_once()
            api.poll_component_states.reset_mock()
            await coord._send_slow_poll("clu1")
            assert await coord.async_refresh_clu_state("clu1")
            assert bool(schedule_reads(api)) == (enabled and mode == 2)
            assert entity.schedule_polling_enabled == enabled
            assert set(entity.decoded_schedule.temperatures) == {22}
        finally:
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("poll_only", [False, True])
@pytest.mark.parametrize("mode", [0, 2])
def test_editor_loads_fresh_schedule_and_cached_snapshot_does_not_expire(
    tmp_path,
    poll_only,
    mode,
):
    async def run():
        hass, coord, entity, api, values = await fixture(
            tmp_path, poll_only=poll_only, mode=mode, schedule_polling_enabled=False
        )
        try:
            await coord.async_setup()
            assert entity.decoded_schedule is None
            entity.entity_id = "climate.living_room"
            flow, entry_patch = make_flow(coord, entity)
            with entry_patch:
                result = await flow.async_step_entity_list({"entity": entity.entity_id})
                assert result["step_id"] == "configure_thermostat"
                field = ui_fields(result)["thermostat"]
                assert field["selector"]["grenton_thermostat"]["schedule_available"]
                assert field["description"]["suggested_value"]["sections"]
                assert len(schedule_reads(api)) == 1
                await flow.async_step_configure_thermostat(
                    {
                        "thermostat": {
                            "cooling_enabled": False,
                            "schedule_polling_enabled": False,
                        }
                    }
                )
                assert len(schedule_reads(api)) == 1
            state = entity.states["scheduleData"]
            key = coord._state_key(state)
            _, stamp = coord._slow_success["clu1"][key]
            coord._slow_success["clu1"][key] = (monotonic() - 1000, stamp)
            assert coord.is_state_fresh(state)
            assert entity.decoded_schedule is not None
            await coord._process_report(
                "clu1", [coord._state_key(entity.states["mode"])], [2]
            )
            assert coord.is_state_fresh(state)
            await coord._send_slow_poll("clu1")
            assert len(schedule_reads(api)) == 1
            values["9"] = "!0" * 672 + "+00:30"
            flow, entry_patch = make_flow(coord, entity)
            with entry_patch:
                await flow.async_step_entity_list({"entity": entity.entity_id})
            assert len(schedule_reads(api)) == 2
            assert set(entity.decoded_schedule.temperatures) == {21}
        finally:
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("poll_only", [False, True])
@pytest.mark.parametrize("power,mode", [(1, 0), (1, 2), (0, 0), (0, 2)])
def test_failed_explicit_refresh_retains_cached_schedule_without_background_retry(
    tmp_path, poll_only, power, mode
):
    async def run():
        hass, coord, entity, api, _ = await fixture(
            tmp_path,
            poll_only=poll_only,
            power=power,
            mode=mode,
            schedule_polling_enabled=False,
        )
        try:
            await coord.async_setup()
            state = entity.states["scheduleData"]
            key = coord._state_key(state)
            assert await coord.async_refresh_clu_state("clu1", required_states=[state])
            assert schedule_reads(api) == [[key]]
            assert set(entity.decoded_schedule.temperatures) == {20}
            read = api.poll_component_states.side_effect
            api.poll_component_states.side_effect = lambda keys: (
                [MISSING_STATE] * len(keys)
            )
            assert not await coord.async_refresh_clu_state(
                "clu1", required_states=[state]
            )
            assert coord.is_state_fresh(state)
            assert set(entity.decoded_schedule.temperatures) == {20}
            api.poll_component_states.side_effect = read
            api.poll_component_states.reset_mock()
            await coord._send_slow_poll("clu1")
            assert await coord.async_refresh_clu_state("clu1")
            assert not schedule_reads(api)
        finally:
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())


def test_failed_editor_read_shows_error_and_sends_no_writes(tmp_path):
    async def run():
        hass, coord, entity, api, _ = await fixture(tmp_path)
        try:
            await coord.async_setup()
            api.poll_component_states.side_effect = lambda keys: [
                MISSING_STATE for key in keys
            ]
            entity.entity_id = "climate.living_room"
            flow, entry_patch = make_flow(coord, entity)
            with entry_patch:
                result = await flow.async_step_entity_list({"entity": entity.entity_id})
                assert result["errors"] == {"base": "cannot_read_configuration"}
                field = ui_fields(result)["thermostat"]
                assert not field["selector"]["grenton_thermostat"]["schedule_available"]
                draft = field["description"]["suggested_value"]
                draft["schedule_polling_enabled"] = False
                result = await flow.async_step_configure_thermostat(
                    {"thermostat": draft}
                )
                assert result["type"] == "create_entry"
                assert not entity.schedule_polling_enabled
            api.execute_action.assert_not_awaited()
        finally:
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())


def test_split_clu_mode_sources_are_loaded_before_conditional_schedule_read(tmp_path):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(
            hass, entry, [make_clu("clu1"), make_clu("clu2", prefix="521")]
        )
        dto = widget()
        dto.object.mode.cluId = "clu2"
        dto.object.state.cluId = "clu2"
        entity = DeviceMapper.to_domain(dto, coord).entities[0]
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

        async def read(keys):
            await asyncio.sleep(0)
            return [values[key.name] for key in keys]

        for api in coord._apis.values():
            api.connect = AsyncMock(return_value=True)
            api.ping = AsyncMock(return_value=True)
            api.disconnect = AsyncMock()
            api.register_component_states = AsyncMock(side_effect=read)
            api.poll_component_states = AsyncMock(side_effect=read)
        try:
            await coord.async_setup()
            assert entity.following_schedule is True
            assert entity.decoded_schedule is not None
            assert len(schedule_reads(coord._apis["clu1"])) == 1
            assert not schedule_reads(coord._apis["clu2"])
            assert await coord.async_refresh_clu_state(
                "clu1", required_states=[entity.states["scheduleData"]]
            )
            assert entity.schedule_status == "ready"
            assert len(schedule_reads(coord._apis["clu1"])) == 2
        finally:
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())
