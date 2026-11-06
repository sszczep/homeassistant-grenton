"""Cooling capability, native options popup and grouped schedule updates."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.config_entries import OptionsFlowManager
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from probatio import Invalid
from test_on_off_configuration import coordinator
from test_scene_configuration import make_flow, ui_fields
from test_thermostat_v2 import payloads, widget

from custom_components.homeassistant_grenton.domain.entities.thermostat_configuration import (
    GrentonThermostatSelector,
    schedule_sections,
    sections_schedule,
)
from custom_components.homeassistant_grenton.domain.thermostat_schedule import (
    DAYS,
    decode_schedule,
)
from custom_components.homeassistant_grenton.dto.widgets.thermostat_v2 import (
    GrentonWidgetThermostatV2Dto,
)
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper


def thermostat(
    imported=False, options=None, values=None, alias="setControlDirectionAction"
):
    dto = widget().model_dump()
    if imported:
        dto["object"]["controlDirection"] = {**dto["object"]["mode"], "index": "7"}
        dto["object"].pop("setControlDirectionAction", None)
        dto["object"][alias] = {**dto["object"]["setModeAction"], "index": "7"}
    coord = coordinator(options)
    feedback = {
        "6": 1,
        "7": 0,
        "8": 0,
        "9": "Y0" * 672 + "+00:30",
        "10": 0,
        "11": 30,
        "13": 1,
        **(values or {}),
    }
    coord.get_value_for_component.side_effect = lambda state: feedback.get(state.index)
    pending = {}

    async def write(action, **kwargs):
        if action.index in ("9", "10", "11"):
            pending[action.index] = (
                action.value if action.index == "9" else float(action.value)
            )

    async def refresh(*args, **kwargs):
        feedback.update(pending)
        pending.clear()
        return True

    coord.execute_action.side_effect = write
    coord.async_refresh_clu_state = AsyncMock(side_effect=refresh)
    entity = DeviceMapper.to_domain(
        GrentonWidgetThermostatV2Dto.model_validate(dto), coord
    ).entities[0]
    entity.entity_id = "climate.living_room"
    return entity, coord


@pytest.mark.parametrize("alias", ["setControlDirectionAction", "setControlDirection"])
def test_complete_import_enables_cooling_and_accepts_both_action_names(alias):
    entity, _ = thermostat(imported=True, alias=alias, values={"7": 1})
    assert entity.cooling_enabled
    assert entity.hvac_modes == [
        HVACMode.OFF,
        HVACMode.HEAT,
        HVACMode.COOL,
        HVACMode.AUTO,
    ]
    assert entity.hvac_mode == HVACMode.COOL
    assert entity.hvac_action == HVACAction.COOLING


def test_partial_import_keeps_cooling_disabled_and_uses_attribute_seven_fallback():
    dto = widget().model_dump()
    dto["object"]["controlDirection"] = {**dto["object"]["mode"], "index": "7"}
    entity = DeviceMapper.to_domain(
        GrentonWidgetThermostatV2Dto.model_validate(dto), coordinator()
    ).entities[0]
    assert not entity.cooling_enabled
    assert entity.actions["setControlDirectionAction"].index == "7"


@pytest.mark.parametrize("saved", [None, True, False])
def test_schedule_polling_defaults_to_enabled_for_existing_thermostats(saved):
    config = {"cooling_enabled": False}
    if saved is not None:
        config["schedule_polling_enabled"] = saved
    entity, _ = thermostat(options={"entities": {"thermostat1_climate": config}})
    assert entity.schedule_polling_enabled == (saved is not False)
    draft = ui_fields(
        {"data_schema": entity._get_schema_instance()._build(config, {}).schema}
    )["thermostat"]["description"]["suggested_value"]
    assert draft["schedule_polling_enabled"] == (saved is not False)


@pytest.mark.parametrize("invalid", [None, 0, 1, "false", "true", [], {}])
def test_schedule_polling_selector_requires_a_real_boolean(invalid):
    entity, _ = thermostat()
    selector = GrentonThermostatSelector(entity._get_schema_instance().settings)
    with pytest.raises(Invalid):
        selector.configuration(
            {"cooling_enabled": False, "schedule_polling_enabled": invalid}
        )


def test_popup_can_disable_polling_without_schedule_feedback_or_clu_writes():
    entity, coord = thermostat(values={"9": None, "10": None})
    flow, entry_patch = make_flow(coord, entity)

    async def run():
        with entry_patch:
            form = await flow.async_step_entity_list({"entity": entity.entity_id})
            field = ui_fields(form)["thermostat"]
            assert not field["selector"]["grenton_thermostat"]["schedule_available"]
            draft = field["description"]["suggested_value"]
            assert draft["schedule_polling_enabled"] is True
            draft["schedule_polling_enabled"] = False
            result = await flow.async_step_configure_thermostat({"thermostat": draft})
            assert result["type"] == "create_entry"
            assert (
                result["data"]["entities"][entity.unique_id]["schedule_polling_enabled"]
                is False
            )
            assert not entity.schedule_polling_enabled
            coord.execute_action.assert_not_called()

    asyncio.run(run())


def test_saved_false_overrides_import_and_saved_true_enables_omitted_bindings():
    key = "thermostat1_climate"
    entity, _ = thermostat(
        imported=True, options={"entities": {key: {"cooling_enabled": False}}}
    )
    assert HVACMode.COOL not in entity.hvac_modes
    entity, coord = thermostat(options={"entities": {key: {"cooling_enabled": True}}})
    assert entity.cooling_enabled
    asyncio.run(entity.async_set_hvac_mode(HVACMode.COOL))
    assert payloads(coord) == [
        'THERMOSTAT1:set(7,"1")',
        'THERMOSTAT1:set(8,"0")',
        'THERMOSTAT1:set(6,"1")',
    ]


def test_mode_commands_select_direction_only_for_manual_heat_or_cool():
    entity, coord = thermostat(imported=True, values={"7": 1, "8": 2})

    async def run():
        await entity.async_set_hvac_mode(HVACMode.HEAT)
        await entity.async_set_hvac_mode(HVACMode.AUTO)
        await entity.async_turn_off()
        await entity.async_turn_on()

    asyncio.run(run())
    assert payloads(coord) == [
        'THERMOSTAT1:set(7,"0")',
        'THERMOSTAT1:set(8,"0")',
        'THERMOSTAT1:set(6,"1")',
        'THERMOSTAT1:set(8,"2")',
        'THERMOSTAT1:set(6,"1")',
        'THERMOSTAT1:set(6,"0")',
        'THERMOSTAT1:set(6,"1")',
    ]


@pytest.mark.parametrize("direction, value", [("heating", "0"), ("cooling", "1")])
def test_popup_direction_change_preserves_auto_mode_and_power(direction, value):
    entity, coord = thermostat(values={"8": 2})
    selector = GrentonThermostatSelector(entity._get_schema_instance().settings)
    config = selector.configuration(
        {"cooling_enabled": True, "control_direction": direction}
    )
    options = asyncio.run(entity.apply_configuration(config))
    assert payloads(coord) == [f'THERMOSTAT1:set(7,"{value}")']
    assert entity.hvac_mode == HVACMode.AUTO
    assert options["entities"][entity.unique_id] == {
        "cooling_enabled": True,
        "schedule_polling_enabled": True,
    }


@pytest.mark.parametrize(
    "direction, output, expected",
    [
        (1, 1, HVACAction.COOLING),
        (1, 0, HVACAction.IDLE),
        (0, 1, HVACAction.HEATING),
        (None, 1, None),
        (3, 1, None),
    ],
)
def test_auto_feedback_uses_direction_and_control_output(direction, output, expected):
    entity, _ = thermostat(imported=True, values={"8": 2, "7": direction, "13": output})
    assert entity.hvac_mode == HVACMode.AUTO
    assert entity.hvac_action == expected
    assert entity.extra_state_attributes["control_direction_name"] == (
        "heating" if direction == 0 else "cooling" if direction == 1 else None
    )


def test_cooling_setpoints_are_manual_only_and_direction_write_failure_stops_activation():
    entity, coord = thermostat(imported=True, values={"7": 1})
    asyncio.run(entity.async_set_temperature(temperature=23.5))
    assert payloads(coord) == ['THERMOSTAT1:set(3,"23.5")']
    entity, coord = thermostat(imported=True, values={"8": 2})
    with pytest.raises(ServiceValidationError):
        asyncio.run(
            entity.async_set_temperature(temperature=23.5, hvac_mode=HVACMode.COOL)
        )
    coord.execute_action.assert_not_called()
    coord.execute_action.side_effect = HomeAssistantError("No CLU")
    with pytest.raises(HomeAssistantError):
        asyncio.run(entity.async_set_hvac_mode(HVACMode.COOL))
    assert payloads(coord) == ['THERMOSTAT1:set(7,"1")']


def editor():
    return GrentonThermostatSelector(
        {
            "cooling_available": True,
            "schedule_available": True,
            "minimum": 10,
            "maximum": 30,
        }
    )


def sections():
    return [{"days": list(DAYS), "periods": [{"time": "00:00", "temperature": 20}]}]


@pytest.mark.parametrize(
    "bad",
    [
        [],
        sections() * 8,
        [{"days": ["monday"], "periods": [{"time": "00:00", "temperature": 20}]}],
        sections() * 2,
        [{"days": [], "periods": []}],
        [{"days": ["monday", "monday"], "periods": []}],
    ],
)
def test_day_groups_reject_missing_overlapping_empty_or_excess_sections(bad):
    with pytest.raises(Invalid):
        sections_schedule(bad)


@pytest.mark.parametrize(
    "periods",
    [
        [],
        [{"time": "00:00", "temperature": 20}] * 97,
        [{"time": "00:15", "temperature": 20}],
        [{"time": "24:00", "temperature": 20}],
        [{"time": "00:00", "temperature": 20}, {"time": "12:10", "temperature": 22}],
        [{"time": "00:00", "temperature": 20}, {"time": "00:00", "temperature": 22}],
        [{"time": "00:00", "temperature": 20.1}],
        [{"time": "00:00", "temperature": 9.5}],
        [{"time": "00:00", "temperature": 30.5}],
        [{"time": "00:00", "temperature": True}],
    ],
)
def test_editor_validates_period_bounds_order_resolution_and_temperatures(periods):
    draft = sections()
    draft[0]["periods"] = periods
    with pytest.raises(Invalid):
        editor()({"cooling_enabled": False, "edit_schedule": True, "sections": draft})


def test_seven_sections_with_96_periods_each_round_trip_through_grouping():
    schedule = {
        day: [
            {
                "time": f"{slot // 4:02}:{slot % 4 * 15:02}",
                "temperature": 10 + slot / 2 % 20,
            }
            for slot in range(96)
        ]
        for day in DAYS
    }
    grouped = [{"days": [day], "periods": periods} for day, periods in schedule.items()]
    assert (
        editor().configuration(
            {"cooling_enabled": True, "edit_schedule": True, "sections": grouped}
        )["schedule"]
        == schedule
    )
    assert sections_schedule(schedule_sections(schedule)) == schedule


def test_popup_prefills_groups_and_saves_one_complete_week_without_changing_mode():
    entity, coord = thermostat(values={"7": 1, "8": 2})
    flow, entry_patch = make_flow(coord, entity)

    async def run():
        with entry_patch:
            listing = await flow.async_step_entity_list()
            assert (
                entity.entity_id
                in ui_fields(listing)["entity"]["selector"]["grenton_entity"][
                    "include_entities"
                ]
            )
            result = await flow.async_step_entity_list({"entity": entity.entity_id})
            assert result["step_id"] == "configure_thermostat"
            field = ui_fields(result)["thermostat"]
            draft = field["description"]["suggested_value"]
            assert len(draft["sections"]) == 1
            assert not draft["edit_schedule"]
            draft.update(cooling_enabled=True, edit_schedule=True)
            draft["sections"][0]["periods"] = [
                {"time": "00:00", "temperature": 21},
                {"time": "09:00", "temperature": 23.5},
            ]
            result = await flow.async_step_configure_thermostat({"thermostat": draft})
            assert result["type"] == "create_entry"
            assert result["data"]["entities"][entity.unique_id] == {
                "cooling_enabled": True,
                "schedule_polling_enabled": True,
            }
            assert entity.cooling_enabled

    asyncio.run(run())
    assert len(payloads(coord)) == 1
    written = coord.execute_action.await_args.args[0]
    assert written.index == "9"
    assert written.value.endswith("+00:30")
    expected = [
        {"time": "00:00", "temperature": 21},
        {"time": "09:00", "temperature": 23.5},
    ]
    assert all(
        periods == expected
        for periods in decode_schedule(written.value, 30).periods().values()
    )


def test_native_options_manager_sends_the_schedule_after_its_schema_validation(
    tmp_path,
):
    """HA validates the selector before the integration's generic flow does."""

    async def run():
        entity, coord = thermostat(values={"8": 2, "7": 1})
        flow, entry_patch = make_flow(coord, entity)
        entry = coord.config_entry
        entry.entry_id = "interface1"
        entry.update_listeners = []
        hass = HomeAssistant(str(tmp_path))
        hass.config_entries = SimpleNamespace(
            async_get_known_entry=Mock(return_value=entry),
            async_update_entry=Mock(return_value=True),
            async_schedule_reload=Mock(),
        )
        flow.hass = hass
        flow.handler = entry.entry_id
        manager = OptionsFlowManager(hass)
        manager._async_add_flow_progress(flow)
        with entry_patch:
            await manager._async_handle_step(
                flow, "entity_list", {"entity": entity.entity_id}
            )
            draft = {
                "cooling_enabled": False,
                "edit_schedule": True,
                "control_direction": "unchanged",
                "sections": sections(),
            }
            draft["sections"][0]["periods"] = [
                {"time": "00:00", "temperature": 21},
                {"time": "09:00", "temperature": 23.5},
            ]
            result = await manager.async_configure(flow.flow_id, {"thermostat": draft})
        assert result["type"] == "create_entry"
        coord.execute_action.assert_awaited_once()
        written = coord.execute_action.await_args.args[0]
        assert written.index == "9"
        assert all(
            periods == draft["sections"][0]["periods"]
            for periods in decode_schedule(written.value, 30).periods().values()
        )
        assert entity.hvac_mode == HVACMode.AUTO
        assert entity.control_direction_name == "cooling"
        await hass.async_stop()

    asyncio.run(run())


def test_failed_schedule_save_keeps_draft_popup_open_and_does_not_save_cooling():
    entity, coord = thermostat()
    flow, entry_patch = make_flow(coord, entity)
    draft = {"cooling_enabled": True, "edit_schedule": True, "sections": sections()}
    coord.execute_action.side_effect = HomeAssistantError("CLU offline")

    async def run():
        with entry_patch:
            await flow.async_step_entity_list({"entity": entity.entity_id})
            result = await flow.async_step_configure_thermostat(
                {"thermostat": deepcopy(draft)}
            )
            assert result["type"] == "form"
            assert result["errors"] == {"base": "cannot_apply_configuration"}
            assert (
                ui_fields(result)["thermostat"]["description"]["suggested_value"]
                == draft
            )
            assert not entity.cooling_enabled
            # Cancelling the schedule edit after a failed write must discard it.
            draft["edit_schedule"] = False
            result = await flow.async_step_configure_thermostat({"thermostat": draft})
            assert result["type"] == "create_entry"
            assert entity.cooling_enabled
            assert coord.execute_action.await_count == 1

    asyncio.run(run())


def test_cooling_configuration_without_schedule_feedback_never_writes_the_clu():
    entity, coord = thermostat(values={"9": None, "10": None})
    schema = entity._get_schema_instance()
    assert not schema.settings["schedule_available"]
    selector = GrentonThermostatSelector(schema.settings)
    config = selector.configuration({"cooling_enabled": True, "edit_schedule": False})
    asyncio.run(entity.apply_configuration(config))
    coord.execute_action.assert_not_called()
    with pytest.raises(Invalid):
        selector(
            {"cooling_enabled": True, "edit_schedule": True, "sections": sections()}
        )


def test_popup_sorts_the_submitted_copy_without_reordering_the_editor_draft():
    periods = [
        {"time": "00:00", "temperature": 20},
        {"time": "18:15", "temperature": 22},
        {"time": "13:30", "temperature": 19},
    ]
    draft = {
        "cooling_enabled": False,
        "edit_schedule": True,
        "sections": [{"days": list(DAYS), "periods": periods}],
    }
    original = deepcopy(draft)
    selector = editor()
    assert selector(selector(draft)) == original
    config = selector.configuration(draft)
    for day in DAYS:
        assert config["schedule"][day] == [periods[0], periods[2], periods[1]]
    assert draft == original
