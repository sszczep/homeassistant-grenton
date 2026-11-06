"""THERMOSTAT_V2 discovery, heating state and CLU action bindings."""

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
from test_clu_scripts import make_entry
from test_on_off_configuration import coordinator

from custom_components.homeassistant_grenton import PLATFORMS, climate
from custom_components.homeassistant_grenton.domain.api.clu_messages.action import (
    GrentonCluApiActionRequest,
)
from custom_components.homeassistant_grenton.dto.page import GrentonPageDto
from custom_components.homeassistant_grenton.dto.widgets.thermostat_v2 import (
    GrentonWidgetThermostatV2Dto,
)
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper


def widget():
    """Public test fixture with the same indexes as the supplied widget."""
    bindings = {}
    for name, index in {
        "state": 6,
        "mode": 8,
        "currentTemperature": 14,
        "targetTemperature": 12,
        "minTemperature": 10,
        "maxTemperature": 11,
        "controlOutValue": 13,
        "scheduleData": 9,
    }.items():
        bindings[name] = {
            "cluId": "clu1",
            "objectName": "THERMOSTAT1",
            "index": str(index),
            "callType": "ATTRIBUTE",
        }
        if name not in ("currentTemperature", "controlOutValue"):
            action_name = f"set{name[0].upper()}{name[1:]}Action"
            bindings[action_name] = {
                **bindings[name],
                "value": "$value$",
                "event": "CLICK",
                "index": "3" if name == "targetTemperature" else str(index),
            }
    return GrentonWidgetThermostatV2Dto(
        id="thermostat1", label="Living room", icon="temperature", object=bindings
    )


def thermostat(**values):
    coord = coordinator()
    values = {"8": 0, **values}
    coord.get_value_for_component.side_effect = lambda state: values.get(state.index)
    pending = {}

    async def write(action, **kwargs):
        if action.index in ("9", "10", "11"):
            pending[action.index] = (
                action.value if action.index == "9" else float(action.value)
            )

    async def refresh(*args, **kwargs):
        values.update(pending)
        pending.clear()
        return True

    coord.execute_action.side_effect = write
    coord.async_refresh_clu_state = AsyncMock(side_effect=refresh)
    device = DeviceMapper.to_domain(widget(), coord)
    return device.entities[0], coord


def payloads(coord):
    return [
        GrentonCluApiActionRequest.from_action(call.args[0]).payload
        for call in coord.execute_action.call_args_list
    ]


def test_page_discovers_thermostat_and_registers_all_heating_feedback():
    page = GrentonPageDto(
        name="Heating",
        icon="default",
        isFullscreenWidget=False,
        widgets=[widget().model_dump()],
    )
    coord = coordinator()
    device = DeviceMapper.to_domain(page.widgets[0], coord)
    entity = device.entities[0]
    assert isinstance(entity, ClimateEntity)
    assert entity.unique_id == "thermostat1_climate"
    assert entity.device_info["model"] == "THERMOSTAT_V2"
    assert entity.device_info["name"] == "Living room"
    assert entity.name is None
    assert {
        call.args[0].index for call in coord.register_component_state.call_args_list
    } == {
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
        "12",
        "13",
        "14",
    }
    assert entity.hvac_modes == [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
    assert not entity.supported_features & ClimateEntityFeature.PRESET_MODE
    assert entity.target_temperature_step == 0.5
    assert entity.temperature_unit == "°C"


@pytest.mark.parametrize(
    "state, output, mode, action",
    [
        (0, 1, HVACMode.OFF, HVACAction.OFF),
        ("0", "0", HVACMode.OFF, HVACAction.OFF),
        (1, 1, HVACMode.HEAT, HVACAction.HEATING),
        ("1", "0", HVACMode.HEAT, HVACAction.IDLE),
        (1, None, HVACMode.HEAT, None),
        (1, 0.5, HVACMode.HEAT, None),
        (None, 1, None, None),
        ("", "", None, None),
        (2, 1, None, None),
    ],
)
def test_heat_and_idle_use_control_output_instead_of_comparing_temperatures(
    state, output, mode, action
):
    entity, _ = thermostat(**{"6": state, "13": output, "12": 21, "14": 22})
    assert entity.hvac_mode == mode
    assert entity.hvac_action == action


@pytest.mark.parametrize(
    "mode, expected",
    [(0, HVACMode.HEAT), (2, HVACMode.AUTO), (1, None), (3, None), (None, None)],
)
def test_only_confirmed_modes_are_mapped_to_hvac_modes(mode, expected):
    entity, _ = thermostat(**{"6": 1, "8": mode, "13": 1})
    assert entity.hvac_mode == expected
    assert entity.hvac_action == HVACAction.HEATING
    assert entity.extra_state_attributes["grenton_mode"] == mode


def test_temperature_and_bounds_use_distinct_read_bindings():
    entity, _ = thermostat(**{"14": "21.3", "12": 24.5, "10": "10", "11": 30})
    assert entity.current_temperature == 21.3
    assert entity.target_temperature == 24.5
    assert entity.min_temp == 10
    assert entity.max_temp == 30


@pytest.mark.parametrize("value", [None, "", "nil", "bad", True, "nan", "inf", "-inf"])
def test_invalid_feedback_never_becomes_a_temperature(value):
    entity, _ = thermostat(**{"14": value, "12": value})
    assert entity.current_temperature is None
    assert entity.target_temperature is None


def test_power_preserves_mode_and_explicit_heat_and_auto_select_the_mode():
    entity, coord = thermostat(**{"8": 2})

    async def run():
        await entity.async_turn_on()
        await entity.async_turn_off()
        await entity.async_set_hvac_mode(HVACMode.HEAT)
        await entity.async_set_hvac_mode(HVACMode.AUTO)

    asyncio.run(run())
    assert payloads(coord) == [
        'THERMOSTAT1:set(6,"1")',
        'THERMOSTAT1:set(6,"0")',
        'THERMOSTAT1:set(7,"0")',
        'THERMOSTAT1:set(8,"0")',
        'THERMOSTAT1:set(6,"1")',
        'THERMOSTAT1:set(8,"2")',
        'THERMOSTAT1:set(6,"1")',
    ]
    assert all(action.value == "$value$" for action in entity.actions.values())
    assert all(
        call.kwargs == {"raise_on_error": True}
        for call in coord.execute_action.call_args_list
    )


def test_unsupported_modes_and_failed_writes_are_reported():
    entity, coord = thermostat()
    with pytest.raises(ServiceValidationError):
        asyncio.run(entity.async_set_hvac_mode(HVACMode.COOL))
    coord.execute_action.assert_not_called()
    coord.execute_action.side_effect = HomeAssistantError("CLU unavailable")
    with pytest.raises(HomeAssistantError, match="CLU unavailable"):
        asyncio.run(entity.async_turn_on())


def test_manual_target_write_changes_neither_mode_nor_power():
    entity, coord = thermostat(**{"6": 0, "8": 0, "10": 10, "11": 30})
    asyncio.run(entity.async_set_temperature(temperature=22.5))
    assert payloads(coord) == [
        'THERMOSTAT1:set(3,"22.5")',
    ]
    assert entity.actions["setTargetTemperatureAction"].value == "$value$"


@pytest.mark.parametrize("mode", [2, 1, 3, None])
@pytest.mark.parametrize("enabled", [0, 1])
def test_auto_and_unknown_modes_disable_target_controls_and_reject_writes(
    mode, enabled
):
    entity, coord = thermostat(**{"6": enabled, "8": mode})
    assert not entity.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
    with pytest.raises(ServiceValidationError, match="Select Heat"):
        asyncio.run(entity.async_set_temperature(temperature=22.5))
    coord.execute_action.assert_not_called()


def test_auto_with_temperature_is_rejected_before_changing_either_setting():
    entity, coord = thermostat()
    with pytest.raises(ServiceValidationError, match="Select Heat"):
        asyncio.run(
            entity.async_set_temperature(temperature=22.5, hvac_mode=HVACMode.AUTO)
        )
    coord.execute_action.assert_not_called()


def test_combined_heat_and_temperature_cannot_bypass_the_auto_lock():
    entity, coord = thermostat(**{"6": 1, "8": 2})
    with pytest.raises(ServiceValidationError, match="Select Heat"):
        asyncio.run(
            entity.async_set_temperature(temperature=22.5, hvac_mode=HVACMode.HEAT)
        )
    coord.execute_action.assert_not_called()


def test_manual_target_step_accepts_conversion_noise_and_writes_exact_half_degrees():
    entity, coord = thermostat()
    asyncio.run(entity.async_set_temperature(temperature=22.50000001))
    assert payloads(coord) == ['THERMOSTAT1:set(3,"22.5")']


@pytest.mark.parametrize("mode, state", [(HVACMode.HEAT, "1"), (HVACMode.OFF, "0")])
def test_setting_temperature_and_hvac_mode_sets_manual_target_before_power(mode, state):
    entity, coord = thermostat(**{"10": 10, "11": 30})
    asyncio.run(entity.async_set_temperature(temperature=23, hvac_mode=mode))
    assert payloads(coord) == (
        ['THERMOSTAT1:set(3,"23.0")']
        + (
            ['THERMOSTAT1:set(7,"0")', 'THERMOSTAT1:set(8,"0")']
            if mode == HVACMode.HEAT
            else []
        )
        + [f'THERMOSTAT1:set(6,"{state}")']
    )


@pytest.mark.parametrize(
    "temperature", ["bad", True, "nan", "inf", 9.9, 30.1, 23.1, 22.25]
)
def test_invalid_target_temperatures_do_not_write_anything(temperature):
    entity, coord = thermostat(**{"10": 10, "11": 30})
    with pytest.raises(ServiceValidationError):
        asyncio.run(entity.async_set_temperature(temperature=temperature))
    coord.execute_action.assert_not_called()


def test_invalid_combined_mode_does_not_write_target():
    entity, coord = thermostat()
    with pytest.raises(ServiceValidationError):
        asyncio.run(
            entity.async_set_temperature(temperature=22, hvac_mode=HVACMode.COOL)
        )
    coord.execute_action.assert_not_called()


def test_failed_target_write_stops_before_selecting_manual_or_turning_on():
    entity, coord = thermostat(**{"10": 10, "11": 30})
    coord.execute_action.side_effect = HomeAssistantError("CLU unavailable")
    with pytest.raises(HomeAssistantError):
        asyncio.run(
            entity.async_set_temperature(temperature=22, hvac_mode=HVACMode.HEAT)
        )
    assert payloads(coord) == ['THERMOSTAT1:set(3,"22.0")']


def test_temperature_calls_without_a_target_can_change_only_power():
    entity, coord = thermostat()
    asyncio.run(entity.async_set_temperature(hvac_mode=HVACMode.HEAT))
    asyncio.run(entity.async_set_temperature())
    assert payloads(coord) == [
        'THERMOSTAT1:set(7,"0")',
        'THERMOSTAT1:set(8,"0")',
        'THERMOSTAT1:set(6,"1")',
    ]


def test_concurrent_temperature_changes_keep_their_commands_together():
    entity, coord = thermostat(**{"10": 10, "11": 30})

    async def execute(*args, **kwargs):
        await asyncio.sleep(0)

    coord.execute_action.side_effect = execute

    async def run():
        await asyncio.gather(
            entity.async_set_temperature(temperature=21, hvac_mode=HVACMode.OFF),
            entity.async_set_temperature(temperature=24, hvac_mode=HVACMode.HEAT),
        )

    asyncio.run(run())
    assert payloads(coord) == [
        'THERMOSTAT1:set(3,"21.0")',
        'THERMOSTAT1:set(6,"0")',
        'THERMOSTAT1:set(3,"24.0")',
        'THERMOSTAT1:set(7,"0")',
        'THERMOSTAT1:set(8,"0")',
        'THERMOSTAT1:set(6,"1")',
    ]


def test_climate_platform_adds_only_climate_entities():
    entity, _ = thermostat()
    entry = SimpleNamespace(
        runtime_data=SimpleNamespace(
            devices=[
                SimpleNamespace(entities=[object(), entity]),
            ]
        )
    )
    added = []
    asyncio.run(
        climate.async_setup_entry(
            Mock(), entry, lambda entities: added.extend(entities)
        )
    )
    assert added == [entity]
    assert "climate" in PLATFORMS


def test_native_climate_entity_registration_and_state(tmp_path):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        entry = make_entry()
        hass.config_entries = SimpleNamespace(async_get_entry=lambda entry_id: entry)
        dr.async_setup(hass)
        await asyncio.gather(
            dr.async_load(hass, load_empty=True), er.async_load(hass, load_empty=True)
        )
        entity, coord = thermostat(**{"6": 1, "8": 2, "13": 0, "14": 21.2, "12": 23.5})
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
        state = hass.states.get(entity.entity_id)
        assert state.state == "auto"
        assert state.attributes["current_temperature"] == 21.2
        assert "temperature" not in state.attributes
        assert state.attributes["scheduled_target_temperature_celsius"] == 23.5
        assert state.attributes["hvac_action"] == "idle"
        assert "preset_mode" not in state.attributes
        assert (
            not state.attributes["supported_features"]
            & ClimateEntityFeature.TARGET_TEMPERATURE
        )
        await entity.apply_configuration({"cooling_enabled": True})
        coord.get_value_for_component.side_effect = lambda source: {
            "6": 1,
            "7": 1,
            "8": 2,
            "13": 1,
            "14": 21.2,
            "12": 23.5,
        }.get(source.index)
        entity._handle_coordinator_update()
        cooling_state = hass.states.get(entity.entity_id)
        assert cooling_state.state == "auto"
        assert cooling_state.attributes["control_direction_name"] == "cooling"
        assert cooling_state.attributes["hvac_action"] == "cooling"
        assert "cool" in cooling_state.attributes["hvac_modes"]
        coord.get_value_for_component.side_effect = lambda source: {
            "6": 1,
            "7": 0,
            "8": 0,
            "13": 0,
            "14": 21.2,
            "12": 22.5,
        }.get(source.index)
        entity._handle_coordinator_update()
        state = hass.states.get(entity.entity_id)
        assert state.state == "heat"
        assert state.attributes["temperature"] == 22.5
        assert (
            state.attributes["supported_features"]
            & ClimateEntityFeature.TARGET_TEMPERATURE
        )
        assert "scheduled_target_temperature_celsius" not in state.attributes
        await platform.async_reset()
        await hass.async_stop()

    asyncio.run(run())
