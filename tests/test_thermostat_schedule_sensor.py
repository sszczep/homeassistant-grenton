"""Native schedule sensor, clock boundaries, localization and CLU feedback."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from test_clu_scripts import make_entry
from test_on_off_configuration import coordinator
from test_thermostat_v2 import widget

from custom_components.homeassistant_grenton import sensor as sensor_platform
from custom_components.homeassistant_grenton.domain.entities.thermostat_schedule_sensor import (
    GrentonThermostatScheduleSensor,
)
from custom_components.homeassistant_grenton.domain.thermostat_schedule import (
    decode_schedule,
)
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper

WARSAW = ZoneInfo("Europe/Warsaw")
DAY = "Y0" * 36 + "(0" * 44 + "Y0" * 16
WEEK = "!0" * 96 + DAY * 5 + "!0" * 96 + "+00:30"


def make_sensor(**overrides):
    values = {"6": 1, "7": 0, "8": 2, "9": WEEK, "11": 30, **overrides}
    coord = coordinator()
    coord.get_value_for_component.side_effect = lambda state: values.get(state.index)
    device = DeviceMapper.to_domain(widget(), coord)
    climate, schedule = device.entities[:2]
    schedule._now = Mock(return_value=datetime(2026, 10, 19, 14, 30, tzinfo=WARSAW))
    return device, climate, schedule, coord, values


def test_schedule_is_discovered_on_the_existing_device_without_extra_subscriptions():
    device, climate, schedule, coord, _ = make_sensor()
    assert isinstance(schedule, GrentonThermostatScheduleSensor)
    assert climate.unique_id == "thermostat1_climate"
    assert climate.name is None
    assert schedule.unique_id == "thermostat1_schedule"
    assert schedule.device_info["identifiers"] == climate.device_info["identifiers"]
    assert device.name == "Living room"
    assert coord.register_component_state.call_count == 9
    coord.execute_action.assert_not_called()


def test_sensor_shows_current_period_next_change_and_all_seven_days():
    _, _, schedule, _, _ = make_sensor()
    assert schedule.native_value == "22°C until 20:00"
    attributes = schedule.extra_state_attributes
    assert attributes["following_schedule"] is True
    assert attributes["direction"] == "heating"
    assert attributes["scheduled_target"] == "22°C"
    assert attributes["next_target"] == "20°C"
    assert attributes["next_change"] == "2026-10-19T20:00:00+02:00"
    weekdays = "00:00–09:00: 20°C · 09:00–20:00: 22°C · 20:00–24:00: 20°C"
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        assert attributes[day] == weekdays
    assert attributes["saturday"] == attributes["sunday"] == "00:00–24:00: 21°C"


@pytest.mark.parametrize(
    "power, mode, following",
    [
        (1, 0, False),
        (0, 2, False),
        (1, 2, True),
        (1, 1, False),
        (1, 3, False),
        (None, 2, None),
    ],
)
def test_manual_off_and_unknown_modes_retain_the_saved_schedule(power, mode, following):
    _, _, schedule, _, _ = make_sensor(**{"6": power, "8": mode, "7": 1, "12": 29})
    assert schedule.native_value == "22°C until 20:00"
    assert schedule.extra_state_attributes["following_schedule"] is following
    assert schedule.extra_state_attributes["direction"] == "cooling"
    assert schedule.extra_state_attributes["scheduled_target"] == "22°C"


@pytest.mark.parametrize(
    "data, maximum", [(None, 30), ("bad", 30), (WEEK, None), (WEEK, 33), (WEEK, 0)]
)
def test_missing_or_invalid_schedule_clears_values_instead_of_showing_old_data(
    data, maximum
):
    _, _, schedule, _, values = make_sensor()
    assert schedule.native_value is not None
    values.update({"9": data, "11": maximum})
    assert schedule.native_value is None
    assert schedule.extra_state_attributes == {
        "following_schedule": True,
        "direction": "heating",
    }


def test_constant_schedule_has_no_invented_next_change_and_updates_from_clu_data():
    _, _, schedule, coord, values = make_sensor()
    values["9"] = "!0" * 672 + "+00:30"
    assert schedule.native_value == "21°C all week"
    assert schedule.extra_state_attributes["next_change"] is None
    assert schedule.extra_state_attributes["next_target"] is None
    coord.execute_action.assert_not_called()


def test_summary_labels_and_temperatures_follow_installation_language_and_units():
    _, _, schedule, _, _ = make_sensor()
    schedule.hass = SimpleNamespace(
        config=SimpleNamespace(language="pl", units=US_CUSTOMARY_SYSTEM)
    )
    assert schedule.native_value == "71.6°F do 20:00"
    assert schedule.extra_state_attributes["next_target"] == "68°F"
    assert schedule.extra_state_attributes["monday"].startswith("00:00–09:00: 68°F")


def test_sensor_clock_uses_the_installation_timezone_instead_of_the_host_timezone():
    _, _, schedule, _, _ = make_sensor()
    del schedule._now
    schedule.hass = SimpleNamespace(
        config=SimpleNamespace(time_zone="America/New_York")
    )
    assert schedule._now().tzinfo == ZoneInfo("America/New_York")


def test_summary_names_the_next_day_and_does_not_mistake_midnight_for_a_change():
    _, _, schedule, _, _ = make_sensor()
    schedule._now.return_value = datetime(2026, 10, 18, 23, 45, tzinfo=WARSAW)
    assert schedule.native_value == "21°C until Mon 00:00"
    data = "Y0" * 96 + "(0" * (96 * 2 + 24) + "Y0" * (96 * 4 - 24) + "+00:30"
    decoded = decode_schedule(data, 30)
    active = decoded.active_period(datetime(2026, 10, 19, 22, 30, tzinfo=WARSAW))
    assert active.temperature == 22
    assert active.next_change == datetime(2026, 10, 21, 6, tzinfo=WARSAW)
    assert active.next_temperature == 20


def test_quarter_hour_and_saturday_to_sunday_week_rollover():
    decoded = decode_schedule(WEEK, 30)
    before = decoded.active_period(datetime(2026, 10, 19, 8, 59, 59, tzinfo=WARSAW))
    after = decoded.active_period(datetime(2026, 10, 19, 9, tzinfo=WARSAW))
    assert before.temperature == 20 and before.next_temperature == 22
    assert after.temperature == 22 and after.next_temperature == 20
    week = decode_schedule("!0" * 96 + "Y0" * 576 + "+00:30", 30)
    last = week.active_period(datetime(2026, 10, 24, 23, 45, tzinfo=WARSAW))
    assert last.next_change == datetime(2026, 10, 25, 0, tzinfo=WARSAW)
    assert last.next_temperature == 21


def test_spring_dst_skips_nonexistent_periods():
    data = "Y0" * 8 + "(0" * 4 + "+0" * 84 + "Y0" * 576 + "+00:30"
    active = decode_schedule(data, 30).active_period(
        datetime(2026, 3, 29, 1, 45, tzinfo=WARSAW)
    )
    assert active.temperature == 20
    assert active.next_change.isoformat() == "2026-03-29T03:00:00+02:00"
    assert active.next_temperature == 23


def test_next_change_can_skip_a_whole_week_when_its_only_period_is_in_the_dst_gap():
    data = "Y0" * 8 + "(0" + "Y0" * 663 + "+00:30"
    now = datetime(2026, 3, 22, 2, 15, tzinfo=WARSAW)
    active = decode_schedule(data, 30).active_period(now)
    assert active.temperature == 20
    assert active.next_change.isoformat() == "2026-04-05T02:00:00+02:00"
    assert active.next_temperature == 22


def test_fall_dst_repeats_the_local_period_in_the_second_hour():
    data = "Y0" * 10 + "(0" * 86 + "Y0" * 576 + "+00:30"
    now = datetime(2026, 10, 25, 2, 45, tzinfo=WARSAW, fold=0)
    active = decode_schedule(data, 30).active_period(now)
    assert active.temperature == 22
    assert active.next_change.isoformat() == "2026-10-25T02:00:00+01:00"
    assert active.next_change.astimezone(UTC) > now.astimezone(UTC)
    assert active.next_temperature == 20


def test_next_change_can_be_in_the_following_week():
    data = "(0" + "Y0" * 671 + "+00:30"
    now = datetime(2026, 10, 18, 0, 15, tzinfo=WARSAW)
    active = decode_schedule(data, 30).active_period(now)
    assert active.next_change == datetime(2026, 10, 25, 0, tzinfo=WARSAW)
    assert active.next_temperature == 22


def test_schedule_clock_requires_an_explicit_timezone():
    with pytest.raises(ValueError, match="time zone"):
        decode_schedule(WEEK, 30).active_period(datetime(2026, 10, 19, 14, 30))


@pytest.mark.parametrize(
    "language, sensor_name", [("en", "Schedule"), ("pl", "Harmonogram")]
)
def test_native_sensor_registration_shares_device_preserves_climate_id_and_removes_timer(
    tmp_path, language, sensor_name
):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        hass.config.language = language
        entry = make_entry()
        hass.config_entries = SimpleNamespace(async_get_entry=lambda entry_id: entry)
        dr.async_setup(hass)
        await asyncio.gather(
            dr.async_load(hass, load_empty=True), er.async_load(hass, load_empty=True)
        )
        device, climate, schedule, coord, values = make_sensor()
        translations = json.loads(
            (
                Path(__file__).parents[1]
                / "custom_components/homeassistant_grenton/translations"
                / f"{language}.json"
            ).read_text()
        )["entity"]["sensor"]["thermostat_schedule"]
        assert translations["name"] == sensor_name
        assert {
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        } <= translations["state_attributes"].keys()
        coord.config_entry = entry
        registry = er.async_get(hass)
        old = registry.async_get_or_create(
            "climate", "grenton", climate.unique_id, suggested_object_id="living_room"
        )
        entry.runtime_data = SimpleNamespace(devices=[device], clu_entities=[])
        # Setup logs may inspect names before HA attaches the entity.
        assert schedule.name == "Living room"
        platforms = []
        cancel = Mock()
        with patch(
            "custom_components.homeassistant_grenton.domain.entities.thermostat_schedule_sensor.async_track_time_change",
            return_value=cancel,
        ) as track:
            for domain, entities in (("climate", [climate]), ("sensor", [schedule])):
                platform = EntityPlatform(
                    hass=hass,
                    logger=logging.getLogger(__name__),
                    domain=domain,
                    platform_name="grenton",
                    platform=None,
                    scan_interval=timedelta(seconds=30),
                    entity_namespace=None,
                )
                platform.config_entry = entry
                key = "component.grenton.entity.sensor.thermostat_schedule.name"
                platform.platform_data.platform_translations = {key: sensor_name}
                platform.platform_data.object_id_platform_translations = {
                    key: "Schedule"
                }
                platform.platform_data.default_language_platform_translations = {
                    key: "Schedule"
                }
                await platform.async_add_entities(entities)
                platforms.append(platform)
            assert climate.entity_id == old.entity_id
            assert schedule.registry_entry.device_id == climate.registry_entry.device_id
            assert len(dr.async_get(hass).devices) == 1
            state = hass.states.get(schedule.entity_id)
            assert state.attributes["friendly_name"] == f"Living room {sensor_name}"
            assert state.attributes["following_schedule"] is True
            assert "unit_of_measurement" not in state.attributes
            assert "state_class" not in state.attributes
            assert (
                hass.states.get(climate.entity_id).attributes["friendly_name"]
                == "Living room"
            )
            track.assert_called_once_with(
                hass, schedule._refresh_time, minute=[0, 15, 30, 45], second=0
            )
            schedule._now.return_value = datetime(2026, 10, 19, 20, tzinfo=WARSAW)
            track.call_args.args[1](schedule._now.return_value)
            assert (
                hass.states.get(schedule.entity_id).attributes["scheduled_target"]
                == "20°C"
            )
            values["9"] = "!0" * 672 + "+00:30"
            values["8"] = 0
            schedule._handle_coordinator_update()
            assert (
                hass.states.get(schedule.entity_id).attributes["following_schedule"]
                is False
            )
            assert (
                hass.states.get(schedule.entity_id).attributes["monday"]
                == "00:00–24:00: 21°C"
            )
            for platform in reversed(platforms):
                await platform.async_reset()
        cancel.assert_called_once()
        coord.execute_action.assert_not_called()
        coord.async_refresh_clu_state.assert_not_awaited()
        await hass.async_stop()

    asyncio.run(run())


def test_sensor_platform_discovers_the_schedule_but_not_the_climate_control():
    device, _, _, _, _ = make_sensor()
    entry = SimpleNamespace(
        runtime_data=SimpleNamespace(devices=[device], clu_entities=[])
    )
    added = []
    asyncio.run(
        sensor_platform.async_setup_entry(
            Mock(), entry, lambda entities: added.extend(entities)
        )
    )
    assert added == device.entities[1:]
