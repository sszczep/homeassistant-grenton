"""Descriptive device names and native registry rename behavior."""

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.components.config.device_registry import websocket_update_device
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
from test_clu_scripts import make_entry
from test_on_off_configuration import coordinator, widget
from test_value_v2_configuration import double_widget
from test_value_v2_configuration import widget as value_widget

from custom_components.homeassistant_grenton import _cleanup_orphans
from custom_components.homeassistant_grenton.domain.devices.base import (
    BaseGrentonDevice,
)
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper


@pytest.mark.parametrize(
    "dto, expected",
    [
        (widget(), "Office 0"),
        (widget(double=True), "Office 0 · Office 1"),
        (value_widget(), "Front door"),
        (double_widget(), "Front door · Garage door"),
    ],
)
def test_widget_devices_use_entity_labels_and_keep_the_type_as_model(dto, expected):
    device = DeviceMapper.to_domain(dto, coordinator())
    assert device.name == expected
    for entity in device.entities:
        assert entity.device_info["name"] == expected
        assert entity.device_info["model"] == dto.type
        assert entity.device_info["identifiers"] == {("grenton", dto.id)}
        assert "translation_key" not in entity.device_info
        assert entity.has_entity_name is True
        assert entity.name == (None if len(device.entities) == 1 else entity.label)


@pytest.mark.parametrize(
    "labels, expected",
    [
        ([" Light ", "Light"], "Light"),
        (["A", "B", "C", "D"], "A · B (+2)"),
        (["", " "], "VALUE_V2 (widget1)"),
    ],
)
def test_name_summary_deduplicates_labels_and_handles_empty_and_large_widgets(
    labels, expected
):
    device = BaseGrentonDevice(
        "VALUE_V2", "widget1", [SimpleNamespace(label=label) for label in labels]
    )
    assert device.name == expected


@pytest.mark.parametrize("double", [False, True])
def test_native_device_name_migration_and_rename_preserve_ids_rooms_and_entity_names(
    tmp_path,
    double,
):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        entry = make_entry()
        hass.config_entries = SimpleNamespace(async_get_entry=lambda entry_id: entry)
        dr.async_setup(hass)
        await asyncio.gather(
            dr.async_load(hass, load_empty=True), er.async_load(hass, load_empty=True)
        )
        await ar.async_load(hass, load_empty=True)
        room = ar.async_get(hass).async_create("Biuro")
        coord = coordinator()
        coord.config_entry = entry
        devices = dr.async_get(hass)
        entities = er.async_get(hass)
        device_id = entity_ids = None
        for phase in ("legacy", "automatic", "refresh"):
            dto = widget(double=double)
            if phase == "refresh":
                dto.components[0].label = "Office main"
            device = DeviceMapper.to_domain(dto, coord)
            if phase == "legacy":
                for entity in device.entities:
                    entity.device_info["name"] = "ON_OFF_DOUBLE"
                    entity._attr_has_entity_name = True
                    entity._use_device_name = False
            else:
                _cleanup_orphans(hass, entry, [device], [])
            platform = EntityPlatform(
                hass=hass,
                logger=logging.getLogger(__name__),
                domain="switch",
                platform_name="grenton",
                platform=None,
                scan_interval=timedelta(seconds=30),
                entity_namespace=None,
            )
            platform.config_entry = entry
            await platform.async_add_entities(device.entities)
            current_ids = [entity.entity_id for entity in device.entities]
            current_device_id = device.entities[0].registry_entry.device_id
            if phase == "legacy":
                device_id, entity_ids = current_device_id, current_ids
                devices.async_update_device(device_id, area_id=room.id)
                entities.async_update_entity(entity_ids[0], name="Desk light")
            else:
                assert current_ids == entity_ids
                assert current_device_id == device_id
                assert devices.async_get(device_id).area_id == room.id
                assert (
                    hass.states.get(entity_ids[0]).attributes["friendly_name"]
                    == "Desk light"
                )
                if double:
                    assert hass.states.get(entity_ids[1]).attributes[
                        "friendly_name"
                    ] == (
                        "Office 0 · Office 1 Office 1"
                        if phase == "automatic"
                        else "Office lighting Office 1"
                    )
                registered = devices.async_get(device_id)
                if phase == "automatic":
                    assert registered.name == device.name
                    assert registered.name_by_user is None
                    connection = SimpleNamespace(
                        user=SimpleNamespace(is_admin=True), send_message=Mock()
                    )
                    websocket_update_device(
                        hass,
                        connection,
                        {
                            "id": 1,
                            "type": "config/device_registry/update",
                            "device_id": device_id,
                            "name_by_user": "Office lighting",
                        },
                    )
                    result = connection.send_message.call_args.args[0]
                    assert result["success"] is True
                    assert result["result"]["name_by_user"] == "Office lighting"
                    assert result["result"]["name"] == device.name
                else:
                    assert registered.name == device.name
                    assert registered.name_by_user == "Office lighting"
                    connection = SimpleNamespace(
                        user=SimpleNamespace(is_admin=True), send_message=Mock()
                    )
                    websocket_update_device(
                        hass,
                        connection,
                        {
                            "id": 2,
                            "type": "config/device_registry/update",
                            "device_id": device_id,
                            "name_by_user": None,
                        },
                    )
                    registered = devices.async_get(device_id)
                    assert registered.name_by_user is None
                    assert registered.name == device.name
                    assert registered.area_id == room.id
            await platform.async_reset()
        assert len(er.async_entries_for_config_entry(entities, entry.entry_id)) == len(
            entity_ids
        )

    asyncio.run(run())


def test_native_device_rename_requires_admin():
    with pytest.raises(Unauthorized):
        websocket_update_device(
            None, SimpleNamespace(user=SimpleNamespace(is_admin=False)), {"id": 1}
        )


def test_single_value_entity_uses_device_name_without_repeating_label(tmp_path):
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
        coord.get_value_for_component.return_value = 1
        device = DeviceMapper.to_domain(value_widget(), coord)
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
        await platform.async_add_entities(device.entities)
        entity = device.entities[0]
        assert (
            hass.states.get(entity.entity_id).attributes["friendly_name"]
            == "Front door"
        )
        device_id = entity.registry_entry.device_id
        dr.async_get(hass).async_update_device(device_id, name_by_user="Entrance")
        await hass.async_block_till_done()
        assert (
            hass.states.get(entity.entity_id).attributes["friendly_name"] == "Entrance"
        )
        await platform.async_reset()

    asyncio.run(run())
