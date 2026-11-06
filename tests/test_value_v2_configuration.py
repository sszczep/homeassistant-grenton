"""VALUE_V2 domain selection, numeric conversion and HA metadata validation."""

import asyncio
import json
import logging
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import OptionsFlowManager
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
from homeassistant.helpers.translation import async_get_translations
from probatio import to_field_list
from test_clu_scripts import make_entry
from test_on_off_configuration import coordinator

from custom_components.homeassistant_grenton import _cleanup_orphans
from custom_components.homeassistant_grenton.dto.value import GrentonValueVariableDto
from custom_components.homeassistant_grenton.dto.widgets.value_double import (
    GrentonWidgetValueDoubleDto,
)
from custom_components.homeassistant_grenton.dto.widgets.value_v2 import (
    GrentonWidgetValueV2Dto,
)
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper
from custom_components.homeassistant_grenton.options_flow import GrentonOptionsFlow


def widget(value_type="INTEGER"):
    return GrentonWidgetValueV2Dto(
        id="front_door",
        label="Front door",
        icon="door",
        unit="UNKNOWN",
        valueType=value_type,
        precision=0,
        object={
            "value": {
                "callType": "ATTRIBUTE",
                "cluId": "clu2",
                "objectName": "DIN_1",
                "index": "3",
            }
        },
    )


def double_widget():
    left = widget().model_dump(
        include={"label", "icon", "unit", "valueType", "precision", "object"}
    )
    right = widget("FLOAT").model_dump(
        include={"label", "icon", "unit", "valueType", "precision", "object"}
    )
    right["label"] = "Garage door"
    right["object"]["value"]["index"] = "4"
    return GrentonWidgetValueDoubleDto(
        id="front_door", componentLeft=left, componentRight=right
    )


@pytest.mark.parametrize("value_type", ["FLOAT", "INTEGER"])
@pytest.mark.parametrize(
    "device_class, expected",
    [
        ("enum", None),
        ("timestamp", None),
        ("energy", None),
        ("temperature", SensorStateClass.MEASUREMENT),
        (None, SensorStateClass.MEASUREMENT),
    ],
)
def test_numeric_state_class_obeys_ha_device_class(value_type, device_class, expected):
    coord = coordinator(
        {
            "entities": {
                "front_door_0": {
                    "device_class": device_class,
                    "unit_of_measurement": "stale",
                }
            }
        }
    )
    entity = DeviceMapper.to_domain(widget(value_type), coord).entities[0]
    assert entity.state_class == expected
    if device_class == "enum":
        assert entity.native_unit_of_measurement is None


@pytest.mark.parametrize(
    "value, expected",
    [
        (0, True),
        ("0", True),
        ("0.0", True),
        (1, False),
        (800, False),
        ("2", False),
        (0.25, False),
        ("0.25", False),
        (-1, True),
        (False, True),
        (True, False),
        (None, None),
        ("", None),
        ("bad", None),
        ("nan", None),
        (float("inf"), None),
        (float("-inf"), None),
    ],
)
def test_binary_sensor_converts_numeric_values_and_preserves_subscription(
    value, expected
):
    coord = coordinator(
        {
            "entities": {
                "front_door_0": {"entity_type": "binary_sensor", "device_class": "door"}
            }
        }
    )
    entity = DeviceMapper.to_domain(widget(), coord).entities[0]
    assert isinstance(entity, BinarySensorEntity)
    assert not isinstance(entity, SensorEntity)
    assert entity.device_class == BinarySensorDeviceClass.DOOR
    coord.get_value_for_component.return_value = value
    assert entity.is_on is expected
    assert (
        entity.state_object.clu_id,
        entity.state_object.object_name,
        entity.state_object.index,
    ) == ("clu2", "DIN_1", "3")
    coord.register_component_state.assert_called_once_with(entity.state_object)


def fields(form):
    return {
        field["name"]: field
        for field in to_field_list(
            form["data_schema"], custom_serializer=cv.custom_serializer
        )
    }


@pytest.mark.parametrize("widget_factory", [widget, double_widget])
@pytest.mark.parametrize("invert_state", [False, True])
def test_integration_options_flow_switches_domains_and_clears_incompatible_settings(
    tmp_path,
    widget_factory,
    invert_state,
):
    async def run():
        coord = coordinator(
            {
                "other": True,
                "entities": {
                    "front_door_0": {
                        "device_class": "enum",
                        "unit_of_measurement": "V",
                    },
                    "other_0": {"device_class": "temperature"},
                    "front_door_1": {
                        "device_class": "temperature",
                        "unit_of_measurement": "°C",
                    },
                },
            }
        )
        device = DeviceMapper.to_domain(widget_factory(), coord)
        entity = device.entities[0]
        entity.entity_id = "sensor.front_door"
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
        with patch.object(
            GrentonOptionsFlow,
            "config_entry",
            new_callable=PropertyMock,
            return_value=entry,
        ):
            flow = GrentonOptionsFlow()
            flow.hass = hass
            flow.handler = entry.entry_id
            result = await flow.async_step_entity_list({"entity": entity.entity_id})
            assert result["step_id"] == "configure_value_v2_type"
            assert fields(result)["entity_type"]["default"] == "sensor"
            result = await flow.async_step_configure_value_v2_type(
                {"entity_type": "switch"}
            )
            assert result["errors"] == {"entity_type": "invalid_configuration"}
            result = await flow.async_step_configure_value_v2_type(
                {"entity_type": "binary_sensor"}
            )
            assert result["step_id"] == "configure_value_v2_binary"
            assert fields(result)["invert_state"]["default"] is False
            assert "boolean" in fields(result)["invert_state"]["selector"]
            device_class = fields(result)["device_class"]
            assert device_class["default"] == "none"
            assert "door" in device_class["selector"]["select"]["options"]
            assert "enum" not in device_class["selector"]["select"]["options"]
            result = await flow.async_step_configure_value_v2_binary(
                {"device_class": "door", "invert_state": invert_state}
            )
            assert result["type"] == "create_entry"
            assert result["data"]["entities"][entity.unique_id] == {
                "entity_type": "binary_sensor",
                "read_mode": "realtime",
                "device_class": "door",
                "invert_state": invert_state,
            }
            assert result["data"]["other"] is True
            assert result["data"]["entities"]["front_door_1"] == {
                "device_class": "temperature",
                "unit_of_measurement": "°C",
            }
            assert result["data"]["entities"]["other_0"] == {
                "device_class": "temperature"
            }
            await OptionsFlowManager(hass).async_finish_flow(flow, result)
            hass.config_entries.async_schedule_reload.assert_called_once_with(
                entry.entry_id
            )
            entry.options = result["data"]
            restored = DeviceMapper.to_domain(widget_factory(), coord)
            restored.entities[0].entity_id = "binary_sensor.front_door"
            entry.runtime_data.devices = [restored]
            flow = GrentonOptionsFlow()
            result = await flow.async_step_entity_list(
                {"entity": restored.entities[0].entity_id}
            )
            assert fields(result)["entity_type"]["default"] == "binary_sensor"
            result = await flow.async_step_configure_value_v2_type(
                {"entity_type": "binary_sensor"}
            )
            assert fields(result)["invert_state"]["default"] is invert_state
            flow = GrentonOptionsFlow()
            await flow.async_step_entity_list(
                {"entity": restored.entities[0].entity_id}
            )
            result = await flow.async_step_configure_value_v2_type(
                {"entity_type": "sensor"}
            )
            assert result["step_id"] == "configure_sensor_class"
            assert "invert_state" not in fields(result)
            assert fields(result)["device_class"]["default"] == "none"
            result = await flow.async_step_configure_sensor_class(
                {"device_class": "temperature"}
            )
            assert result["step_id"] == "configure_sensor_unit"
            result = await flow.async_step_configure_sensor_unit(
                {"unit_of_measurement": "°C"}
            )
            assert result["data"]["entities"]["front_door_0"] == {
                "entity_type": "sensor",
                "read_mode": "slow",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
            }

    asyncio.run(run())


def test_native_ha_registration_round_trip_and_enum_has_no_measurement_warning(
    tmp_path, caplog
):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        entry = make_entry()
        hass.config_entries = SimpleNamespace(async_get_entry=lambda entry_id: entry)
        dr.async_setup(hass)
        await asyncio.gather(
            dr.async_load(hass, load_empty=True), er.async_load(hass, load_empty=True)
        )
        coord = coordinator()
        coord.config_entry = entry
        coord.get_value_for_component.return_value = 0
        registry = er.async_get(hass)
        device_id = previous_id = None
        for domain, device_class in [
            ("sensor", "enum"),
            ("binary_sensor", "door"),
            ("sensor", "enum"),
        ]:
            object.__setattr__(
                entry,
                "options",
                MappingProxyType(
                    {
                        "entities": {
                            "front_door_0": {
                                "entity_type": domain,
                                "device_class": device_class,
                            }
                        }
                    }
                ),
            )
            device = DeviceMapper.to_domain(widget(), coord)
            _cleanup_orphans(hass, entry, [device], [])
            if previous_id:
                assert registry.async_get(previous_id) is None
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
            await platform.async_add_entities(device.entities)
            entity = device.entities[0]
            state = hass.states.get(entity.entity_id)
            assert state is not None
            assert state.state == ("on" if domain == "binary_sensor" else "0")
            assert "state_class" not in state.attributes
            assert "unit_of_measurement" not in state.attributes
            assert {
                key: state.attributes[key] for key in ("call_type", "clu_id", "object")
            } == {
                "call_type": "ATTRIBUTE",
                "clu_id": "clu2",
                "object": "DIN_1.3",
            }
            assert (
                not {"state_source", "object_name", "index", "variable_name"}
                & state.attributes.keys()
            )
            assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == 1
            if device_id:
                assert entity.registry_entry.device_id == device_id
            device_id = entity.registry_entry.device_id
            previous_id = entity.entity_id
            await platform.async_reset()
        assert "impossible considering device class" not in caplog.text

    asyncio.run(run())


@pytest.mark.parametrize("language", ["en", "pl"])
def test_value_v2_type_selection_translations(language):
    data = json.loads(
        (
            Path(__file__).parents[1]
            / "custom_components/homeassistant_grenton/translations"
            / f"{language}.json"
        ).read_text()
    )
    assert data["options"]["step"]["configure_value_v2_type"]["data"]["entity_type"]
    assert set(data["selector"]["value_v2_entity_types"]["options"]) == {
        "sensor",
        "binary_sensor",
    }
    assert data["selector"]["binary_sensor_device_classes"]["options"]["none"]
    assert data["options"]["step"]["configure_value_v2_binary"]["data"]["invert_state"]


@pytest.mark.parametrize("binary_index", [0, 1])
def test_double_values_have_independent_domains_types_and_subscriptions(binary_index):
    coord = coordinator(
        {
            "entities": {
                f"front_door_{binary_index}": {
                    "entity_type": "binary_sensor",
                    "device_class": "door",
                }
            }
        }
    )
    device = DeviceMapper.to_domain(double_widget(), coord)
    assert len(device.entities) == 2
    binary = device.entities[binary_index]
    sensor = device.entities[1 - binary_index]
    assert isinstance(binary, BinarySensorEntity)
    assert isinstance(sensor, SensorEntity)
    assert binary.device_info == sensor.device_info == device.device_info
    assert [entity.unique_id for entity in device.entities] == [
        "front_door_0",
        "front_door_1",
    ]
    coord.get_value_for_component.side_effect = lambda state: (
        "0" if state.index == "3" else "2.5"
    )
    assert binary.is_on is (binary_index == 0)
    assert sensor.native_value == (0 if binary_index == 1 else 2.5)
    assert sensor.state_class == SensorStateClass.MEASUREMENT
    assert [
        call.args[0].index for call in coord.register_component_state.call_args_list
    ] == ["3", "4"]


@pytest.mark.parametrize("entity_type", ["sensor", "binary_sensor"])
def test_double_source_attributes_follow_each_channel_and_preserve_sources(entity_type):
    coord = coordinator(
        {
            "entities": {
                f"front_door_{index}": {
                    "entity_type": entity_type,
                    "invert_state": True,
                }
                for index in (0, 1)
            }
        }
    )
    dto = double_widget()
    dto.componentRight.object.value = GrentonValueVariableDto(
        cluId="clu1", objectName="", index="DoorClosed"
    )
    left, right = DeviceMapper.to_domain(dto, coord).entities
    assert left.extra_state_attributes == {
        "call_type": "ATTRIBUTE",
        "clu_id": "clu2",
        "object": "DIN_1.3",
    }
    assert right.extra_state_attributes == {
        "call_type": "VARIABLE",
        "clu_id": "clu1",
        "object": "DoorClosed",
    }
    # Inspecting or altering a returned snapshot cannot change the subscribed source.
    right.extra_state_attributes["object"] = "Other"
    assert right.state_object.index == "DoorClosed"
    assert right.extra_state_attributes["object"] == "DoorClosed"
    assert [call.args[0] for call in coord.register_component_state.call_args_list] == [
        left.state_object,
        right.state_object,
    ]


def test_double_domain_cleanup_keeps_the_other_channel_registration(tmp_path):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        entry = make_entry()
        hass.config_entries = SimpleNamespace(async_get_entry=lambda entry_id: entry)
        dr.async_setup(hass)
        await dr.async_load(hass, load_empty=True)
        await er.async_load(hass, load_empty=True)
        coord = coordinator()
        coord.config_entry = entry
        registry = er.async_get(hass)
        left = registry.async_get_or_create(
            "sensor", "grenton", "front_door_0", config_entry=entry
        )
        right = registry.async_get_or_create(
            "sensor", "grenton", "front_door_1", config_entry=entry
        )
        object.__setattr__(
            entry,
            "options",
            MappingProxyType(
                {
                    "entities": {
                        "front_door_0": {
                            "entity_type": "binary_sensor",
                            "device_class": "door",
                        }
                    }
                }
            ),
        )
        device = DeviceMapper.to_domain(double_widget(), coord)
        _cleanup_orphans(hass, entry, [device], [])
        assert registry.async_get(left.entity_id) is None
        assert registry.async_get(right.entity_id) is right

    asyncio.run(run())


@pytest.mark.parametrize(
    "value, expected",
    [
        (0, False),
        (1, True),
        (2.5, True),
        ("0", False),
        ("1", True),
        (None, None),
        ("", None),
        ("bad", None),
        ("nan", None),
        (float("inf"), None),
    ],
)
def test_inverted_contact_preserves_unknown_values(value, expected):
    coord = coordinator(
        {
            "entities": {
                "front_door_0": {
                    "entity_type": "binary_sensor",
                    "device_class": "door",
                    "invert_state": True,
                }
            }
        }
    )
    entity = DeviceMapper.to_domain(widget(), coord).entities[0]
    coord.get_value_for_component.return_value = value
    assert entity.is_on is expected


def test_double_contacts_can_have_different_polarities():
    coord = coordinator(
        {
            "entities": {
                "front_door_0": {
                    "entity_type": "binary_sensor",
                    "device_class": "door",
                    "invert_state": True,
                },
                "front_door_1": {
                    "entity_type": "binary_sensor",
                    "device_class": "door",
                },
            }
        }
    )
    left, right = DeviceMapper.to_domain(double_widget(), coord).entities
    coord.get_value_for_component.return_value = 1
    assert left.is_on is True
    assert right.is_on is False
    coord.get_value_for_component.return_value = 0
    assert left.is_on is False
    assert right.is_on is True
    coord.get_value_for_component.return_value = None
    assert left.is_on is None
    assert right.is_on is None


@pytest.mark.parametrize(
    "language, expected_label",
    [
        ("en", "Invert state"),
        ("pl", "Odwróć stan"),
    ],
)
@pytest.mark.parametrize("widget_factory", [widget, double_widget])
def test_native_binary_dialog_loads_localized_field_labels(
    tmp_path, language, expected_label, widget_factory
):
    async def run():
        coord = coordinator()
        device = DeviceMapper.to_domain(widget_factory(), coord)
        for entity in device.entities:
            entity.entity_id = "sensor." + entity.unique_id
        coord.config_entry.runtime_data = SimpleNamespace(devices=[device])
        component = (
            Path(__file__).parents[1] / "custom_components/homeassistant_grenton"
        )
        integration = SimpleNamespace(
            file_path=component, has_translations=True, name="Grenton"
        )
        hass = HomeAssistant(str(tmp_path))
        with patch.object(
            GrentonOptionsFlow,
            "config_entry",
            new_callable=PropertyMock,
            return_value=coord.config_entry,
        ):
            flow = GrentonOptionsFlow()
            flow.hass = hass
            await flow.async_step_entity_list({"entity": device.entities[0].entity_id})
            form = await flow.async_step_configure_value_v2_type(
                {"entity_type": "binary_sensor"}
            )
        # Load the options category exactly as the native HA dialog does,
        # then look up labels using the step ID emitted by the actual flow.
        with patch(
            "homeassistant.helpers.translation.async_get_integrations",
            AsyncMock(return_value={"grenton": integration}),
        ):
            translations = await async_get_translations(
                hass, language, "options", {"grenton"}
            )
        prefix = f"component.grenton.options.step.{form['step_id']}"
        for field in fields(form):
            assert translations[f"{prefix}.data.{field}"]
        assert translations[f"{prefix}.data.invert_state"] == expected_label
        assert translations[f"{prefix}.data_description.invert_state"]
        assert fields(form)["invert_state"]["default"] is False
        assert "boolean" in fields(form)["invert_state"]["selector"]

    asyncio.run(run())
