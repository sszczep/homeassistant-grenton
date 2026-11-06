"""Captured thermostat schedules, report parsing and the native HA action."""

import asyncio
import json
import logging
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import selector
from homeassistant.helpers.entity_platform import EntityPlatform
from test_clu_scripts import make_entry, make_hass
from test_thermostat_v2 import payloads, thermostat

from custom_components.homeassistant_grenton import async_setup
from custom_components.homeassistant_grenton.domain.api.clu_messages.client_register import (
    GrentonCluApiClientRegisterResponse,
    GrentonCluApiClientReportNotification,
)
from custom_components.homeassistant_grenton.domain.thermostat_schedule import (
    DAYS,
    decode_schedule,
    decode_temperature,
    encode_schedule,
    encode_temperature,
)

# Independent expectations transcribed from the supplied myGrenton captures.
CAPTURED = {
    0: "00",
    1: "30",
    2: "60",
    3: "90",
    20: "Y0",
    20.5: "ZJ",
    21: "!0",
    22: "(0",
    23: "+0",
    23.5: ",J",
    24: ".0",
    24.5: "/J",
    25.5: "<J",
    26.5: "?J",
    27: "[0",
    28: "_0",
    29: "|0",
    30: "~~",
}
DEFAULT_DAY = "+0" * 24 + ".0" * 36 + "<J" * 28 + "+0" * 8
SUNDAY = ",J" * 24 + "/J" * 36 + "?J" * 28 + ",J" * 8
MONDAY = "Y0" * 36 + "(0" * 44 + "Y0" * 16
RAMP = "00306090" + "Y0" * 88 + "~~|0_0[0"
RAMP_33 = "SNVpY0 $" + "Y0" * 88 + "~~|p_N?8"
CAPTURED_33 = {
    20: "SN",
    21: "Vp",
    22: "Y0",
    23: " $",
    29: "?8",
    31: "_N",
    32: "|p",
    33: "~~",
}
RAMP_29 = "SsVBYL 6" + "YL" * 88 + "~~{[^-?c"
OBJECT_MANAGER_DAY = "+a" * 24 + ";M" * 16 + ".t" * 48 + "+a" * 8
CAPTURED_29 = {
    17.5: "Ss",
    18.5: "VB",
    19.5: "YL",
    20: " 6",
    25.5: "?c",
    27: "^-",
    28: "{[",
    29: "~~",
}
CAPTURES = [
    DEFAULT_DAY * 7,
    SUNDAY + DEFAULT_DAY * 6,
    SUNDAY + MONDAY + DEFAULT_DAY * 5,
    "Y0" * 672,
    "ZJ" * 672,
    "!0" * 672,
    ("Y0" + "!0" * 95) * 7,
    RAMP + "!0" * 576,
    OBJECT_MANAGER_DAY * 7,
    "X~" * 672,
]


def constant_week(temperature=20):
    return {day: [{"time": "00:00", "temperature": temperature}] for day in DAYS}


@pytest.mark.parametrize("temperature, pair", CAPTURED.items())
def test_temperature_codec_matches_observed_values_including_both_endpoints(
    temperature, pair
):
    assert encode_temperature(temperature, 30) == pair
    assert decode_temperature(pair, 30) == temperature


@pytest.mark.parametrize("week", CAPTURES)
def test_every_captured_schedule_round_trips_without_changing_any_wire_data(week):
    data = week + "+00:30"
    decoded = decode_schedule(data, 30)
    assert len(decoded.temperatures) == 672
    assert encode_schedule(decoded.periods(), data, 0, 30) == data


def test_object_manager_codes_decode_to_mobile_app_half_degree_targets():
    data = OBJECT_MANAGER_DAY * 7 + "+00:30"
    decoded = decode_schedule(data, 30)
    assert all(
        periods
        == [
            {"time": "00:00", "temperature": 23},
            {"time": "06:00", "temperature": 25},
            {"time": "10:00", "temperature": 24},
            {"time": "22:00", "temperature": 23},
        ]
        for periods in decoded.periods().values()
    )


def test_editing_one_period_preserves_other_object_manager_codes_verbatim():
    data = OBJECT_MANAGER_DAY * 7 + "+00:30"
    schedule = decode_schedule(data, 30).periods()
    schedule["monday"][1]["temperature"] = 25.5
    written = encode_schedule(schedule, data, 0, 30)
    start = (96 + 24) * 2
    end = (96 + 40) * 2
    assert written == data[:start] + "<J" * 16 + data[end:]


@pytest.mark.parametrize("pair", ["X~", "Y0"])
def test_default_and_explicit_twenty_degree_schedules_are_both_valid(pair):
    data = pair * 672 + "+00:30"
    decoded = decode_schedule(data, 30)
    assert decoded.periods() == constant_week(20)
    assert encode_schedule(decoded.periods(), data, 0, 30) == data
    assert encode_schedule(constant_week(20.5), data, 0, 30) == "ZJ" * 672 + "+00:30"


@pytest.mark.parametrize("week", [OBJECT_MANAGER_DAY * 7, "X~" * 672, "Y0" * 672])
def test_added_captures_are_ready_in_ha_and_save_without_changing_wire_values(
    week, caplog
):
    data = week + "+00:30"
    entity, coord = thermostat(**{"9": data, "10": 0, "11": 30})
    entity._analyse_schedule()
    assert entity.schedule_status == "ready"
    assert not caplog.records
    schema = entity._get_schema_instance()
    assert schema.settings["schedule_available"]
    assert all(
        period["temperature"] * 2 == round(period["temperature"] * 2)
        for section in schema.sections
        for period in section["periods"]
    )
    asyncio.run(entity.async_set_thermostat_schedule(entity.decoded_schedule.periods()))
    assert coord.execute_action.await_count == 1
    assert coord.execute_action.await_args.args[0].value == data


def test_sunday_first_order_and_quarter_hour_boundaries_match_ramp_capture():
    days = decode_schedule(RAMP + "!0" * 576 + "+00:30", 30).periods()
    assert days["sunday"] == [
        {"time": time, "temperature": temperature}
        for time, temperature in (
            ("00:00", 0),
            ("00:15", 1),
            ("00:30", 2),
            ("00:45", 3),
            ("01:00", 20),
            ("23:00", 30),
            ("23:15", 29),
            ("23:30", 28),
            ("23:45", 27),
        )
    ]
    assert all(days[day] == [{"time": "00:00", "temperature": 21}] for day in DAYS[1:])


@pytest.mark.parametrize("temperature, pair", CAPTURED_33.items())
def test_configured_maximum_changes_encoding_as_observed_in_new_capture(
    temperature, pair
):
    assert encode_temperature(temperature, 33) == pair
    assert decode_temperature(pair, 33) == temperature


def test_twenty_to_thirty_three_capture_decodes_and_round_trips_exactly():
    data = RAMP_33 + "~~" * 576 + "+00:2$"
    decoded = decode_schedule(data, 33)
    assert decoded.periods()["sunday"] == [
        {"time": time, "temperature": temperature}
        for time, temperature in (
            ("00:00", 20),
            ("00:15", 21),
            ("00:30", 22),
            ("00:45", 23),
            ("01:00", 22),
            ("23:00", 33),
            ("23:15", 32),
            ("23:30", 31),
            ("23:45", 29),
        )
    ]
    assert all(
        decoded.periods()[day] == [{"time": "00:00", "temperature": 33}]
        for day in DAYS[1:]
    )
    assert encode_schedule(decoded.periods(), data, 20, 33) == data
    assert encode_schedule(constant_week(20), data, 20, 33) == "SN" * 672 + "+00:2$"


@pytest.mark.parametrize("temperature, pair", CAPTURED_29.items())
def test_second_configured_range_also_matches_observed_half_degree_values(
    temperature, pair
):
    assert encode_temperature(temperature, 29) == pair
    assert decode_temperature(pair, 29) == temperature


def test_ten_to_twenty_nine_capture_decodes_and_round_trips_exactly():
    data = RAMP_29 + "{[" * 576 + "+00:39"
    decoded = decode_schedule(data, 29)
    assert decoded.periods()["sunday"] == [
        {"time": time, "temperature": temperature}
        for time, temperature in (
            ("00:00", 17.5),
            ("00:15", 18.5),
            ("00:30", 19.5),
            ("00:45", 20),
            ("01:00", 19.5),
            ("23:00", 29),
            ("23:15", 28),
            ("23:30", 27),
            ("23:45", 25.5),
        )
    ]
    assert all(
        decoded.periods()[day] == [{"time": "00:00", "temperature": 28}]
        for day in DAYS[1:]
    )
    assert encode_schedule(decoded.periods(), data, 10, 29) == data


@pytest.mark.parametrize("kind", ["register", "notification", "with_keys"])
@pytest.mark.parametrize("trailer", ["+00:2$", "+00:2 "])
def test_quoted_reports_preserve_encoding_spaces_at_both_ends(kind, trailer):
    data = " $" * 672 + trailer
    wire = f'resp:192.0.2.1:00000000:clientReport:0:{{2,"{data}"," 21.5 ",1}}'
    if kind == "with_keys":
        from custom_components.homeassistant_grenton.state import GrentonCluStateVariableKey
        values = GrentonCluApiClientRegisterResponse(wire, [GrentonCluStateVariableKey(str(i)) for i in range(4)]).values
    else:
        cls = (
            GrentonCluApiClientRegisterResponse
            if kind == "register"
            else GrentonCluApiClientReportNotification
        )
        values = cls(wire).values
    assert values == [2, data, 21.5, 1]
    assert len(values[1]) == 1350
    if trailer == "+00:2$":
        assert decode_schedule(values[1], 33).temperatures[0] == 23


def test_old_metadata_cannot_be_written_after_a_maximum_change_even_for_uniform_maximum():
    with pytest.raises(ValueError, match="metadata does not match"):
        encode_schedule(constant_week(22), "~~" * 672 + "+00:30", 20, 33)


def test_minimum_constrains_writes_without_shifting_the_scaling_origin():
    data = "~~" * 672 + "+00:2$"
    assert encode_schedule(constant_week(20), data, 0, 33) == encode_schedule(
        constant_week(20), data, 20, 33
    )
    with pytest.raises(ValueError, match="at least 20"):
        encode_schedule(constant_week(19.5), data, 20, 33)
    # Existing slots remain readable even if the minimum was increased later.
    assert decode_schedule("SN" * 672 + "+00:2$", 33).temperatures[0] == 20


@pytest.mark.parametrize("maximum", [0, -1, float("nan"), float("inf"), None, True])
def test_invalid_maximum_is_rejected_before_encoding(maximum):
    with pytest.raises((TypeError, ValueError)):
        encode_schedule(constant_week(), "~~" * 672 + "+00:2$", 0, maximum)


@pytest.mark.parametrize("minimum", [33, 34, float("nan"), float("inf"), None, True])
def test_invalid_minimum_is_rejected_before_encoding(minimum):
    with pytest.raises((TypeError, ValueError)):
        encode_schedule(constant_week(), "~~" * 672 + "+00:2$", minimum, 33)


def test_replacement_preserves_the_unexplained_terminal_pair():
    original = "!0" * 672 + ";J0:30"
    assert (
        encode_schedule(constant_week(20.5), original, 0, 30) == "ZJ" * 672 + ";J0:30"
    )


@pytest.mark.parametrize(
    "temperature", [True, "20", None, float("nan"), float("inf"), -0.5, 30.5, 20.1]
)
def test_invalid_temperatures_are_rejected(temperature):
    with pytest.raises((TypeError, ValueError)):
        encode_schedule(constant_week(temperature), "!0" * 672 + "+00:30", 0, 30)


@pytest.mark.parametrize(
    "data",
    [
        "",
        "!0" * 671 + "+00:30",
        "!0" * 673 + "+00:30",
        "!0" * 672 + "+00:3\n",
        '"0' * 672 + "+00:30",
    ],
)
def test_unknown_layouts_and_invalid_characters_are_rejected(data):
    with pytest.raises(ValueError):
        decode_schedule(data, 30)


@pytest.mark.parametrize(
    "periods",
    [
        [],
        [{"time": "01:00", "temperature": 20}],
        [{"time": "00:00", "temperature": 20}, {"time": "00:00", "temperature": 21}],
        [{"time": "00:00", "temperature": 20}, {"time": "24:00", "temperature": 21}],
        [{"time": "00:00", "temperature": 20}, {"time": "00:10", "temperature": 21}],
        [
            {"time": "00:00", "temperature": 20},
            {"time": "02:00", "temperature": 21},
            {"time": "01:00", "temperature": 20},
        ],
        [{"time": "00:00", "temperature": 20, "unexpected": 1}],
    ],
)
def test_incomplete_or_ambiguous_days_are_rejected(periods):
    week = constant_week()
    week["sunday"] = periods
    with pytest.raises(ValueError):
        encode_schedule(week, "!0" * 672 + "+00:30", 0, 30)


def test_all_seven_days_are_required_so_updates_never_use_stale_partial_weeks():
    week = constant_week()
    del week["sunday"]
    with pytest.raises(ValueError, match="seven"):
        encode_schedule(week, "!0" * 672 + "+00:30", 0, 30)


@pytest.mark.parametrize(
    "cls, msg_id",
    [
        (GrentonCluApiClientRegisterResponse, "12345678"),
        (GrentonCluApiClientReportNotification, "00000000"),
    ],
)
def test_quoted_schedule_commas_do_not_shift_other_subscription_values(cls, msg_id):
    data = SUNDAY + DEFAULT_DAY * 6 + "+00:30"
    message = f'resp:192.0.2.1:{msg_id}:clientReport:0:{{2,"{data}",21.5,1}}'
    report = cls(message)
    assert report.values == [2, data, 21.5, 1]


@pytest.mark.parametrize("target_kind", ["entity_id", "device_id"])
@pytest.mark.parametrize("maximum", [30, 33, 29])
def test_real_ha_schedule_action_targets_thermostat_without_mode_or_power_writes(
    tmp_path, target_kind, maximum
):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        await async_setup(hass, {})
        minimum, data, temperature, expected_pair, _second_period = {
            30: (
                0,
                DEFAULT_DAY * 7 + "+00:30",
                20.5,
                "ZJ",
                {"time": "06:00", "temperature": 24},
            ),
            33: (
                20,
                RAMP_33 + "~~" * 576 + "+00:2$",
                20,
                "SN",
                {"time": "00:15", "temperature": 21},
            ),
            29: (
                10,
                RAMP_29 + "{[" * 576 + "+00:39",
                20,
                " 6",
                {"time": "00:15", "temperature": 18.5},
            ),
        }[maximum]
        entity, coord = thermostat(
            **{"6": 1, "8": 2, "9": data, "10": minimum, "11": maximum}
        )
        coord.config_entry = entry
        platform = EntityPlatform(
            hass=hass,
            logger=logging.getLogger(__name__),
            domain="climate",
            platform_name="grenton",
            platform=None,
            scan_interval=timedelta(seconds=30),
            entity_namespace=None,
        )
        platform.config_entry = entry
        await platform.async_add_entities([entity])
        target = (
            entity.entity_id
            if target_kind == "entity_id"
            else entity.registry_entry.device_id
        )
        await hass.services.async_call(
            "grenton",
            "set_thermostat_schedule",
            {
                "schedule": constant_week(temperature),
            },
            target={target_kind: target},
            blocking=True,
        )
        assert payloads(coord) == [
            f'THERMOSTAT1:set(9,"{expected_pair * 672}{data[-6:]}")'
        ]
        assert entity.actions["setScheduleDataAction"].value == "$value$"
        assert entity.hvac_mode == "auto"
        assert entity.decoded_schedule.periods() == constant_week(temperature)
        entity._handle_coordinator_update()
        assert hass.states.get(entity.entity_id).attributes[
            "weekly_schedule"
        ] == constant_week(temperature)
        assert entity.min_temp == minimum
        assert entity.max_temp == maximum
        invalid_week = constant_week(20.1)
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                "grenton",
                "set_thermostat_schedule",
                {
                    "schedule": invalid_week,
                },
                target={target_kind: target},
                blocking=True,
            )
        assert coord.execute_action.await_count == 1
        await platform.async_reset()
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"9": "bad", "10": 0, "11": 30},
        {"9": "!0" * 672 + "+00:30", "10": 30, "11": 10},
    ],
)
def test_writes_require_loaded_schedule_and_valid_current_limits(values):
    entity, coord = thermostat(**values)
    with pytest.raises(ServiceValidationError):
        asyncio.run(entity.async_set_thermostat_schedule(constant_week()))
    coord.execute_action.assert_not_called()


@pytest.mark.parametrize("language", ["en", "pl"])
def test_schedule_service_metadata_and_translations(language):
    component = Path(__file__).parents[1] / "custom_components/homeassistant_grenton"
    metadata = yaml.safe_load((component / "services.yaml").read_text())[
        "set_thermostat_schedule"
    ]
    selector.TargetSelector(metadata["target"])
    selector.selector(metadata["fields"]["schedule"]["selector"])(constant_week())
    translations = json.loads((component / f"translations/{language}.json").read_text())
    assert translations["services"]["set_thermostat_schedule"]["fields"]["schedule"][
        "name"
    ]


def test_invalid_schedule_identifies_the_pair_slot_and_reported_maximum():
    with pytest.raises(ValueError) as caught:
        decode_schedule('Y0"1' + "Y0" * 670 + "+00:30", 30)
    message = str(caught.value)
    assert "Invalid encoded schedule temperature" in message
    assert repr('"1') in message
    assert "sunday 00:15" in message
    assert "maximum 30 °C" in message
    assert "trailer '+00:30'" in message
