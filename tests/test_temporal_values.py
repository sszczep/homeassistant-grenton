"""Unix timestamp conversion, native HA validation, and class translations."""

import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers.translation import async_get_translations
from test_clu_scripts import make_clu, make_entry, make_hass
from test_clu_state import coordinator, register_platforms
from test_clu_variables import configure_manager, fields, set_options
from test_on_off_configuration import coordinator as widget_coordinator
from test_value_v2_configuration import double_widget, widget

from custom_components.homeassistant_grenton.domain.entities.clu_variables import (
    GrentonCluVariableSensor,
    normalize_variable,
)
from custom_components.homeassistant_grenton.integration_config import RuntimeData
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper

SAMPLE = 1791468704
EXPECTED = datetime(2026, 10, 8, 14, 11, 44, tzinfo=UTC)


@pytest.mark.parametrize("device_class", ["date", "timestamp", "uptime"])
@pytest.mark.parametrize("grenton_type", ["INTEGER", "FLOAT", "STRING"])
def test_clu_variable_unix_seconds_register_as_native_temporal_sensor(
    tmp_path, device_class, grenton_type
):
    async def run():
        entry = make_entry()
        config = {
            "variable_name": "LastEvent",
            "label": "Last event",
            "grenton_type": grenton_type,
            "device_class": device_class,
            # A saved numeric configuration may still contain an old unit.
            "unit_of_measurement": "s",
        }
        set_options(entry, {"clu_variables": {"clu1": {"last_event": config}}})
        hass = await make_hass(tmp_path, [entry])
        hass.config.time_zone = "Europe/Warsaw"
        clu = make_clu("clu1")
        coord = coordinator(hass, entry, [clu])
        entity = GrentonCluVariableSensor(coord, clu, "last_event", config)
        entry.runtime_data = RuntimeData(coord, [], [entity])
        keys = coord.state.clus[clu.id].get_subscription_order()
        assert entity.native_value is None
        await coord._process_report(clu.id, keys, [str(SAMPLE)])
        assert entity.native_value == (
            EXPECTED.date() if device_class == "date" else EXPECTED
        )
        assert entity.state_class is None
        assert entity.native_unit_of_measurement is None
        platforms = await register_platforms(hass, entry)
        state = hass.states.get(entity.entity_id)
        assert state.state == (
            "2026-10-08" if device_class == "date" else "2026-10-08T14:11:44+00:00"
        )
        assert "state_class" not in state.attributes
        assert "unit_of_measurement" not in state.attributes
        if device_class == "date":
            # UTC October 8 at 22:30 falls on October 9 in Warsaw.
            await coord._process_report(clu.id, keys, [1791498600])
            assert entity.native_value == date(2026, 10, 9)
            assert hass.states.get(entity.entity_id).state == "2026-10-09"
        for invalid in ["", "bad", "nan", float("inf"), True, 1e100]:
            await coord._process_report(clu.id, keys, [invalid])
            assert entity.native_value is None
            assert hass.states.get(entity.entity_id).state == "unknown"
        for platform in platforms:
            await platform.async_reset()

    asyncio.run(run())


@pytest.mark.parametrize("widget_factory", [widget, double_widget])
@pytest.mark.parametrize("device_class", ["date", "timestamp", "uptime"])
def test_value_widgets_share_unix_timestamp_conversion(widget_factory, device_class):
    coord = widget_coordinator(
        {
            "entities": {
                f"front_door_{index}": {
                    "device_class": device_class,
                    "unit_of_measurement": "s",
                }
                for index in (0, 1)
            }
        }
    )
    coord.get_value_for_component.return_value = SAMPLE
    device = DeviceMapper.to_domain(widget_factory(), coord)
    for entity in device.entities:
        assert entity.native_value == (
            EXPECTED.date() if device_class == "date" else EXPECTED
        )
        assert entity.state_class is None
        assert entity.native_unit_of_measurement is None


@pytest.mark.parametrize("device_class", ["date", "timestamp", "uptime"])
def test_temporal_variable_flow_skips_units_and_discards_old_units(
    tmp_path, device_class
):
    async def run():
        entry = make_entry()
        config = {
            "variable_name": "LastEvent",
            "label": "Last event",
            "grenton_type": "INTEGER",
        }
        set_options(entry, {"clu_variables": {"clu1": {"last_event": config}}})
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu1")
        coord = coordinator(hass, entry, [clu])
        entity = GrentonCluVariableSensor(coord, clu, "last_event", config)
        entity.entity_id = "sensor.last_event"
        entry.runtime_data = RuntimeData(coord, [], [entity])
        manager = configure_manager(hass, entry)
        form = await manager.async_init(entry.entry_id)
        form = await manager.async_configure(
            form["flow_id"], {"next_step_id": "entity_list"}
        )
        form = await manager.async_configure(
            form["flow_id"], {"entity": entity.entity_id}
        )
        form = await manager.async_configure(form["flow_id"], config)
        assert (
            device_class
            in fields(form)["device_class"]["selector"]["select"]["options"]
        )
        result = await manager.async_configure(
            form["flow_id"], {"device_class": device_class}
        )
        assert result["type"] == "create_entry"
        assert (
            entry.options["clu_variables"]["clu1"]["last_event"]["device_class"]
            == device_class
        )
        assert "unit_of_measurement" not in normalize_variable(
            {**config, "device_class": device_class, "unit_of_measurement": "s"}
        )

    asyncio.run(run())


@pytest.mark.parametrize("language, label", [("en", "Uptime"), ("pl", "Czas pracy")])
def test_uptime_class_has_native_selector_translation(tmp_path, language, label):
    async def run():
        component = (
            Path(__file__).parents[1] / "custom_components/homeassistant_grenton"
        )
        integration = SimpleNamespace(
            file_path=component, has_translations=True, name="Grenton"
        )
        hass = await make_hass(tmp_path, [])
        with patch(
            "homeassistant.helpers.translation.async_get_integrations",
            AsyncMock(return_value={"grenton": integration}),
        ):
            translations = await async_get_translations(
                hass, language, "selector", {"grenton"}
            )
        assert (
            translations[
                "component.grenton.selector.sensor_device_classes.options.uptime"
            ]
            == label
        )
        data = json.loads((component / f"translations/{language}.json").read_text())
        assert data["entity"]["sensor"]["clu_uptime"]["name"] == label

    asyncio.run(run())
