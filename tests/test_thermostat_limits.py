"""Thermostat range edits and confirmed schedule synchronization."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from test_thermostat_configuration import sections, thermostat
from test_thermostat_schedule import constant_week
from test_thermostat_schedule_sensor import make_sensor
from test_thermostat_v2 import payloads

from custom_components.homeassistant_grenton.domain.entities.thermostat_configuration import (
    GrentonThermostatSelector,
)
from custom_components.homeassistant_grenton.domain.thermostat_schedule import (
    decode_schedule,
)


def test_limits_are_reported_sensors_on_the_same_device_without_new_subscriptions():
    device, climate, _, coord, values = make_sensor(**{"10": 10, "11": 30})
    minimum, maximum = device.entities[2:]
    assert [sensor.unique_id for sensor in (minimum, maximum)] == [
        "thermostat1_min_temperature",
        "thermostat1_max_temperature",
    ]
    for sensor, expected in ((minimum, 10), (maximum, 30)):
        assert sensor.native_value == expected
        assert sensor.device_class == SensorDeviceClass.TEMPERATURE
        assert sensor.native_unit_of_measurement == "°C"
        assert sensor.state_class is None
        assert sensor.device_info == climate.device_info
    values["10"] = "12.5"
    assert minimum.native_value == 12.5
    for bad in (None, "", True, "nan", "inf", "bad"):
        values["11"] = bad
        assert maximum.native_value is None
    assert coord.register_component_state.call_count == 9
    coord.execute_action.assert_not_called()
    for language in ("en", "pl"):
        translations = json.loads(
            (
                Path(__file__).parents[1]
                / "custom_components/homeassistant_grenton/translations"
                / f"{language}.json"
            ).read_text()
        )
        assert translations["entity"]["sensor"][minimum.translation_key]["name"]
        assert translations["entity"]["sensor"][maximum.translation_key]["name"]


def test_editor_limits_are_opt_in_and_validation_is_idempotent_with_new_bounds():
    entity, _ = thermostat()
    schema = entity._get_schema_instance()
    assert schema.settings["limits_available"]
    selector = GrentonThermostatSelector(schema.settings)
    draft = {
        "cooling_enabled": False,
        "edit_limits": True,
        "minimum": 10,
        "maximum": 33,
        "edit_schedule": True,
        "sections": sections(),
    }
    draft["sections"][0]["periods"][0]["temperature"] = 32
    assert selector(selector(draft)) == draft
    assert selector.configuration(draft)["limits"] == {"minimum": 10, "maximum": 33}
    draft["edit_limits"] = False
    from probatio import Invalid

    with pytest.raises(Invalid):
        selector(draft)  # 32 is outside the existing range.


@pytest.mark.parametrize(
    "minimum,maximum",
    [(20, 20), (30, 10), (-1, 30), (0, 0.5), (0, 30.1), (True, 30), (0, float("inf"))],
)
def test_invalid_limits_are_rejected_before_writes(minimum, maximum):
    entity, coord = thermostat()
    with pytest.raises(ServiceValidationError):
        asyncio.run(
            entity.apply_configuration(
                {
                    "cooling_enabled": False,
                    "limits": {"minimum": minimum, "maximum": maximum},
                }
            )
        )
    coord.execute_action.assert_not_called()


def test_changing_maximum_preserves_targets_and_reencodes_metadata_from_captures():
    entity, coord = thermostat(values={"8": 2, "7": 1})
    options = asyncio.run(
        entity.apply_configuration(
            {"cooling_enabled": True, "limits": {"minimum": 10, "maximum": 33}}
        )
    )
    assert payloads(coord) == [
        'THERMOSTAT1:set(10,"10")',
        'THERMOSTAT1:set(11,"33")',
        f'THERMOSTAT1:set(9,"{"SN" * 672}+00:2$")',
    ]
    assert entity.decoded_schedule.periods() == constant_week(20)
    assert entity.hvac_mode == "auto"
    assert entity.control_direction_name == "cooling"
    assert options["entities"][entity.unique_id] == {
        "cooling_enabled": True,
        "schedule_polling_enabled": True,
    }
    assert entity.min_temp == 10 and entity.max_temp == 33
    assert coord.async_refresh_clu_state.await_count == 2


def test_minimum_only_does_not_rewrite_schedule():
    entity, coord = thermostat()
    asyncio.run(
        entity.apply_configuration(
            {"cooling_enabled": False, "limits": {"minimum": 10, "maximum": 30}}
        )
    )
    assert payloads(coord) == ['THERMOSTAT1:set(10,"10")']


@pytest.mark.parametrize(
    "limits,values",
    [
        ({"minimum": 21, "maximum": 30}, {}),
        ({"minimum": 0, "maximum": 19}, {}),
        ({"minimum": 10, "maximum": 30}, {"12": 5}),
    ],
)
def test_range_change_cannot_silently_clamp_saved_schedule_or_manual_target(
    limits, values
):
    entity, coord = thermostat(values=values)
    with pytest.raises(ServiceValidationError):
        asyncio.run(
            entity.apply_configuration({"cooling_enabled": False, "limits": limits})
        )
    coord.execute_action.assert_not_called()


def test_new_schedule_and_disjoint_limits_use_safe_order_and_keep_cooling_auto():
    entity, coord = thermostat(values={"8": 2, "7": 1})
    asyncio.run(
        entity.apply_configuration(
            {
                "cooling_enabled": True,
                "limits": {"minimum": 31, "maximum": 33},
                "schedule": constant_week(32),
            }
        )
    )
    assert [call.args[0].index for call in coord.execute_action.await_args_list] == [
        "11",
        "10",
        "9",
    ]
    assert set(entity.decoded_schedule.temperatures) == {32}
    assert entity.hvac_mode == "auto" and entity.control_direction_name == "cooling"


def test_timeout_during_partial_limit_save_reads_back_actual_device_values():
    entity, coord = thermostat()
    write = coord.execute_action.side_effect

    async def fail_second(action, **kwargs):
        if action.index == "11":
            raise HomeAssistantError("Request timeout")
        await write(action, **kwargs)

    coord.execute_action.side_effect = fail_second
    with pytest.raises(HomeAssistantError, match="timeout"):
        asyncio.run(
            entity.apply_configuration(
                {"cooling_enabled": False, "limits": {"minimum": 10, "maximum": 33}}
            )
        )
    assert entity.min_temp == 10 and entity.max_temp == 30
    assert [call.args[0].index for call in coord.execute_action.await_args_list] == [
        "10",
        "11",
    ]
    assert coord.async_refresh_clu_state.await_count == 2


@pytest.mark.parametrize(
    "mode,direction", [(0, 0), (0, 1), (2, 0), (2, 1), (1, 1), (3, 0)]
)
def test_schedule_save_preserves_all_operating_modes_and_directions(mode, direction):
    entity, coord = thermostat(imported=True, values={"8": mode, "7": direction})
    asyncio.run(entity.async_set_thermostat_schedule(constant_week(22)))
    assert [call.args[0].index for call in coord.execute_action.await_args_list] == [
        "9"
    ]
    assert (
        entity._number("mode") == mode
        and entity._number("controlDirection") == direction
    )
    assert set(entity.decoded_schedule.temperatures) == {22}


def test_schedule_write_checks_once_and_reports_a_delayed_controller_update():
    entity, coord = thermostat()
    refresh = coord.async_refresh_clu_state.side_effect
    attempts = 0

    async def delayed(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            return True  # Old values despite a successful reply.
        return await refresh(*args, **kwargs)

    coord.async_refresh_clu_state.side_effect = delayed
    with pytest.raises(HomeAssistantError, match="did not confirm"):
        asyncio.run(entity.async_set_thermostat_schedule(constant_week(23)))
    assert attempts == 2  # One preflight read, one verification read, no retries.
    assert set(entity.decoded_schedule.temperatures) == {20}


@pytest.mark.parametrize("fresh", [True, False])
def test_unconfirmed_schedule_is_an_error_even_if_a_write_was_acknowledged(
    fresh, caplog
):
    entity, coord = thermostat()
    coord.execute_action.side_effect = None  # ACK, but CLU does not apply it.
    coord.async_refresh_clu_state.side_effect = [True, fresh, fresh, fresh]
    with pytest.raises(HomeAssistantError, match="did not confirm"):
        asyncio.run(entity.async_set_thermostat_schedule(constant_week(23)))
    assert set(entity.decoded_schedule.temperatures) == {20}
    assert coord.execute_action.await_count == 1
    assert entity.label in caplog.text
    assert "scheduleData=clu1/THERMOSTAT1.9" in caplog.text
    assert "minTemperature=clu1/THERMOSTAT1.10" in caplog.text
    assert "maxTemperature=clu1/THERMOSTAT1.11" in caplog.text


def test_failed_initial_read_never_writes_using_stale_cached_schedule():
    entity, coord = thermostat()
    coord.async_refresh_clu_state = AsyncMock(return_value=False)
    with pytest.raises(HomeAssistantError, match="Could not read"):
        asyncio.run(entity.async_set_thermostat_schedule(constant_week(23)))
    coord.execute_action.assert_not_called()


def test_range_and_schedule_feedback_in_either_order_recovers_when_consistent():
    _, entity, schedule, _, values = make_sensor(**{"10": 0})
    values["11"] = 33
    assert entity.decoded_schedule is None
    assert "maximum" in entity.schedule_status
    assert schedule.native_value is None
    values["9"] = "SN" * 672 + "+00:2$"
    assert entity.schedule_status == "ready"
    assert schedule.native_value == "20°C all week"
    values.update({"11": 30, "9": "Y0" * 672 + "+00:30"})
    values["9"] = "SN" * 672 + "+00:2$"
    assert entity.decoded_schedule is None
    values["11"] = 33
    assert (
        decode_schedule(values["9"], 33).temperatures
        == entity.decoded_schedule.temperatures
    )


def test_limit_sensors_use_native_ha_units_and_device_names(tmp_path):
    import logging
    from datetime import timedelta

    from homeassistant.helpers.entity_platform import EntityPlatform
    from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
    from test_clu_scripts import make_entry, make_hass

    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        hass.config.units = US_CUSTOMARY_SYSTEM
        device, _, _, coord, _ = make_sensor(**{"10": 10, "11": 30})
        coord.config_entry = entry
        platform = EntityPlatform(
            hass=hass,
            logger=logging.getLogger(__name__),
            domain="sensor",
            platform_name="grenton",
            platform=None,
            scan_interval=timedelta(seconds=30),
            entity_namespace=None,
        )
        platform.config_entry = entry
        translations = {
            f"component.grenton.entity.sensor.thermostat_{key}.name": name
            for key, name in (
                ("minimum", "Minimum temperature"),
                ("maximum", "Maximum temperature"),
            )
        }
        platform.platform_data.platform_translations = translations
        platform.platform_data.object_id_platform_translations = translations
        platform.platform_data.default_language_platform_translations = translations
        await platform.async_add_entities(device.entities[2:])
        for sensor, value, name in zip(
            device.entities[2:],
            (50, 86),
            ("Minimum temperature", "Maximum temperature"),
        ):
            state = hass.states.get(sensor.entity_id)
            assert float(state.state) == value
            assert state.attributes["unit_of_measurement"] == "°F"
            assert state.attributes["friendly_name"] == f"Living room {name}"
            assert "state_class" not in state.attributes
        assert (
            device.entities[2].registry_entry.device_id
            == device.entities[3].registry_entry.device_id
        )
        await platform.async_reset()
        await hass.async_stop()

    asyncio.run(run())
