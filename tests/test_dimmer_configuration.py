"""DIMMER_V2 brightness templates, source overrides and native options flow."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import pytest
from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import OptionsFlowManager
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from probatio import to_field_list
from test_on_off_configuration import coordinator

from custom_components.homeassistant_grenton.domain.api.clu_messages.action import (
    GrentonCluApiActionRequest,
)
from custom_components.homeassistant_grenton.dto.widgets.dimmer_v2 import (
    GrentonWidgetDimmerV2Dto,
)
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper
from custom_components.homeassistant_grenton.options_flow import GrentonOptionsFlow


def widget(call_type="SCRIPT", maximum=255):
    def action(value, event):
        return {
            "callType": call_type,
            "cluId": "clu1",
            "objectName": "LEDSetValue" if call_type == "SCRIPT" else "LED1",
            "index": "5",
            "event": event,
            "value": f'"livingRoom",{value}' if call_type == "SCRIPT" else value,
        }

    return GrentonWidgetDimmerV2Dto(
        id="led",
        label="LED Salon",
        icon="dimmer",
        min=0,
        max=maximum,
        precision=2,
        object={
            "value": {
                "callType": "ATTRIBUTE",
                "cluId": "clu1",
                "objectName": "LED1",
                "index": "5",
            },
            "onAction": action(str(maximum), "ON"),
            "offAction": action("0", "OFF"),
            "setValueAction": action("$value$", "CLICK"),
        },
    )


def payload(action):
    return GrentonCluApiActionRequest.from_action(action).payload


@pytest.mark.parametrize(
    "call_type, expected",
    [
        ("SCRIPT", 'LEDSetValue("livingRoom",128.0)'),
        ("METHOD", 'LED1:execute(5,"128.0")'),
        ("ATTRIBUTE", 'LED1:set(5,"128.0")'),
        ("VARIABLE", 'setVar("5","128.0")'),
    ],
)
def test_imported_brightness_uses_template_for_all_call_types(call_type, expected):
    async def run():
        coord = coordinator()
        entity = DeviceMapper.to_domain(widget(call_type), coord).entities[0]
        before = deepcopy(entity._config)
        template = payload(entity.action_set_value)
        await entity.async_turn_on(brightness=128)
        await entity.async_turn_on(brightness=64)
        assert payload(coord.execute_action.await_args_list[0].args[0]) == expected
        assert payload(
            coord.execute_action.await_args_list[1].args[0]
        ) == expected.replace("128.0", "64.0")
        assert entity._config == before
        assert payload(entity.action_set_value) == template
        assert isinstance(entity, LightEntity)
        assert entity.supported_color_modes == {ColorMode.BRIGHTNESS}
        attributes = entity.extra_state_attributes
        assert (
            attributes["action_set_value_object"]
            == {
                "SCRIPT": "LEDSetValue",
                "METHOD": "LED1.5",
                "ATTRIBUTE": "LED1.5",
                "VARIABLE": "5",
            }[call_type]
        )
        assert attributes["action_set_value_call_type"] == call_type
        for name in ("action_on", "action_off", "action_set_value"):
            assert attributes[f"{name}_clu_id"] == "clu1"
            assert name not in attributes
            assert f"{name}_value" not in attributes
        assert attributes["object"] == "LED1.5"
        assert "state_source" not in attributes
        assert attributes["brightness_range"] == {"min": 0, "max": 255, "precision": 2}

    asyncio.run(run())


@pytest.mark.parametrize("call_type", ["SCRIPT", "METHOD", "ATTRIBUTE", "VARIABLE"])
def test_plain_on_and_off_preserve_the_imported_commands(call_type):
    async def run():
        coord = coordinator()
        entity = DeviceMapper.to_domain(widget(call_type), coord).entities[0]
        await entity.async_turn_on()
        await entity.async_turn_off()
        await entity.async_turn_on(brightness=0)
        assert [
            payload(call.args[0]) for call in coord.execute_action.await_args_list
        ] == [
            payload(entity.action_on),
            payload(entity.action_off),
            payload(entity.action_off),
        ]

    asyncio.run(run())


@pytest.mark.parametrize("call_type", ["SCRIPT", "METHOD", "ATTRIBUTE", "VARIABLE"])
def test_saved_bindings_preserve_fixed_arguments_and_follow_selected_clu(call_type):
    async def run():
        coord = coordinator(
            {"other_option": True, "entities": {"other": {"unit": "test"}}}
        )
        entity = DeviceMapper.to_domain(widget(), coord).entities[0]
        action = {
            "call_type": call_type,
            "clu_id": "clu2",
            "object_name": "LED2",
            "index": "9",
            "value": "$value$",
        }
        if call_type == "VARIABLE":
            action["variable_name"] = "Brightness"
        if call_type in ("SCRIPT", "METHOD"):
            action["arguments"] = [
                {"type": "string", "value": "bedroom"},
                {"type": "lua", "value": "$value$"},
                {"type": "boolean", "value": False},
            ]
        options = await entity.apply_configuration(
            {
                "state": {
                    "call_type": "VARIABLE",
                    "clu_id": "clu2",
                    "variable_name": "LightLevel",
                },
                "action_on": {
                    "call_type": "SCRIPT",
                    "clu_id": "clu2",
                    "object_name": "Enable",
                    "value": '"bedroom"',
                },
                "action_off": {
                    "call_type": "METHOD",
                    "clu_id": "clu2",
                    "object_name": "Disable",
                    "index": "2",
                    "arguments": [],
                },
                "action_set_value": action,
                "min": 0,
                "max": 1,
                "precision": 2,
            }
        )
        assert options["other_option"] is True
        assert options["entities"]["other"] == {"unit": "test"}
        coord.config_entry.options = options
        coord.register_component_state.reset_mock()
        restored = DeviceMapper.to_domain(widget(), coord).entities[0]
        assert restored.unique_id == entity.unique_id
        assert restored.device_info == entity.device_info
        assert restored.state_object.clu_id == "clu2"
        assert restored.state_object.call_type == "VARIABLE"
        assert restored.state_object.index == "LightLevel"
        coord.register_component_state.assert_called_once_with(restored.state_object)
        coord.get_value_for_component.return_value = "0.5"
        assert restored.brightness == 127
        assert restored.is_on is True
        await restored.async_turn_on(brightness=128)
        await restored.async_turn_on()
        await restored.async_turn_off()
        calls = [call.args[0] for call in coord.execute_action.await_args_list]
        assert all(call.clu_id == "clu2" for call in calls)
        expected = {
            "SCRIPT": 'LED2("bedroom", 0.5, false)',
            "METHOD": 'LED2:execute(9, "bedroom", 0.5, false)',
            "ATTRIBUTE": 'LED2:set(9,"0.5")',
            "VARIABLE": 'setVar("Brightness","0.5")',
        }
        assert [payload(call) for call in calls] == [
            expected[call_type],
            'Enable("bedroom")',
            "Disable:execute(2)",
        ]
        # Templates stay in executable configuration, independent of compact metadata.
        assert "$value$" in payload(restored.action_set_value)
        if call_type in ("SCRIPT", "METHOD"):
            assert restored.extra_state_attributes["action_set_value_args"] == [
                "bedroom",
                "$value$",
                False,
            ]
            assert restored.extra_state_attributes["action_set_value_object"] == (
                "LED2" if call_type == "SCRIPT" else "LED2.9"
            )
        else:
            assert "action_set_value_args" not in restored.extra_state_attributes

    asyncio.run(run())


@pytest.mark.parametrize(
    "value, brightness, on",
    [
        (None, None, None),
        ("bad", None, None),
        ("nan", None, None),
        ("inf", None, None),
        (0, 0, False),
        (128, 128, True),
        (255, 255, True),
        (300, 255, True),
        (-5, 0, False),
    ],
)
def test_brightness_feedback(value, brightness, on):
    coord = coordinator()
    entity = DeviceMapper.to_domain(widget(), coord).entities[0]
    coord.get_value_for_component.return_value = value
    assert entity.brightness == brightness
    assert entity.is_on is on


@pytest.mark.parametrize(
    "value", [None, -1, 256, float("nan"), float("inf"), True, "128"]
)
def test_invalid_brightness_sends_no_command(value):
    coord = coordinator()
    entity = DeviceMapper.to_domain(widget(), coord).entities[0]
    with pytest.raises(ServiceValidationError):
        asyncio.run(entity.async_turn_on(brightness=value))
    coord.execute_action.assert_not_awaited()


def test_options_flow_shows_drafts_validates_saves_and_reloads(tmp_path):
    async def run():
        coord = coordinator({"other_option": True})
        device = DeviceMapper.to_domain(widget(), coord)
        entity = device.entities[0]
        entity.entity_id = "light.led_salon"
        entry = coord.config_entry
        entry.entry_id = "interface1"
        entry.update_listeners = []
        entry.runtime_data = SimpleNamespace(devices=[device])
        hass = HomeAssistant(str(tmp_path))
        hass.config_entries = SimpleNamespace(
            async_get_known_entry=Mock(return_value=entry),
            async_update_entry=Mock(return_value=True),
            async_schedule_reload=Mock(),
        )
        flow = GrentonOptionsFlow()
        flow.hass = hass
        flow.handler = entry.entry_id

        def fields(result):
            return {
                field["name"]: field
                for field in to_field_list(
                    result["data_schema"], custom_serializer=cv.custom_serializer
                )
            }

        with patch.object(
            GrentonOptionsFlow,
            "config_entry",
            new_callable=PropertyMock,
            return_value=entry,
        ):
            result = await flow.async_step_entity_list({"entity": entity.entity_id})
            assert result["step_id"] == "configure_dimmer_state"
            source = fields(result)["state"]
            assert source["description"]["suggested_value"] == entity._config["state"]
            assert source["selector"]["grenton_scene"]["mode"] == "state"
            state_input = {
                key: entity._config[key] for key in ("state", "min", "max", "precision")
            }
            for changes, error_key in [
                ({"max": 0}, "max"),
                ({"min": 256}, "max"),
                ({"precision": 1.5}, "precision"),
                ({"min": float("nan")}, "min"),
            ]:
                result = await flow.async_step_configure_dimmer_state(
                    {**state_input, **changes}
                )
                assert result["errors"] == {error_key: "invalid_configuration"}
            result = await flow.async_step_configure_dimmer_state(state_input)
            for name in ("on", "off"):
                assert result["step_id"] == f"configure_dimmer_{name}_action"
                key = f"action_{name}"
                draft = fields(result)[key]["description"]["suggested_value"]
                assert draft["arguments"][0] == {
                    "type": "string",
                    "value": "livingRoom",
                }
                result = await getattr(
                    flow, f"async_step_configure_dimmer_{name}_action"
                )({key: draft})
            assert result["step_id"] == "configure_dimmer_brightness_action"
            draft = fields(result)["action_set_value"]["description"]["suggested_value"]
            assert draft["arguments"][1] == {"type": "lua", "value": "$value$"}
            bad = {**draft, "arguments": [{"type": "number", "value": 255}]}
            result = await flow.async_step_configure_dimmer_brightness_action(
                {"action_set_value": bad}
            )
            assert result["errors"] == {"action_set_value": "invalid_configuration"}
            assert (
                fields(result)["action_set_value"]["description"]["suggested_value"]
                == bad
            )
            result = await flow.async_step_configure_dimmer_brightness_action(
                {"action_set_value": draft}
            )
            assert result["type"] == "create_entry"
            assert result["data"]["other_option"] is True
            assert coord.config_entry.options == {"other_option": True}
            await OptionsFlowManager(hass).async_finish_flow(flow, result)
        hass.config_entries.async_schedule_reload.assert_called_once_with(
            entry.entry_id
        )
        coord.config_entry.options = result["data"]
        restored = DeviceMapper.to_domain(widget(), coord).entities[0]
        assert restored._config == result["data"]["entities"]["led_0"]
        await restored.async_turn_on(brightness=128)
        assert (
            payload(coord.execute_action.await_args.args[0])
            == 'LEDSetValue("livingRoom", 128.0)'
        )

    asyncio.run(run())


@pytest.mark.parametrize("language", ["en", "pl"])
def test_dimmer_forms_have_translations(language):
    path = (
        Path(__file__).parents[1]
        / "custom_components/homeassistant_grenton/translations"
        / f"{language}.json"
    )
    steps = json.loads(path.read_text())["options"]["step"]
    entity = DeviceMapper.to_domain(widget(), coordinator()).entities[0]
    for step in entity._get_schema_instance().steps:
        form = step.builder(entity._config, {})
        translations = steps[step.step_id]
        assert translations["title"]
        assert translations["description"]
        assert {
            field["name"]
            for field in to_field_list(
                form.schema, custom_serializer=cv.custom_serializer
            )
        } == set(translations["data"])
