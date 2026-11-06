"""Generic sensors retain user-selected units through HA flows and reloads."""

import asyncio

import pytest
from homeassistant.data_entry_flow import InvalidData
from test_clu_scripts import make_entry, make_hass
from test_clu_state import coordinator, make_clu, register_platforms
from test_clu_variables import (
    configure_manager,
    open_clu_variables,
    set_options,
    variable_entry,
)
from test_integration_configuration import fields
from test_value_v2_configuration import double_widget, widget

from custom_components.homeassistant_grenton.domain.entities.clu_variables import (
    custom_variable_entities,
)
from custom_components.homeassistant_grenton.integration_config import RuntimeData
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper


@pytest.mark.parametrize("widget_factory", [widget, double_widget])
@pytest.mark.parametrize(
    "unit, expected",
    [("%", "%"), ("steps", "steps"), ("none", None), ("", None), (" % ", "%")],
)
def test_generic_widget_unit_flow_reloads_as_native_ha_sensor(
    tmp_path, widget_factory, unit, expected
):
    async def run():
        entry = make_entry()
        sibling = {"device_class": "temperature", "unit_of_measurement": "°C"}
        set_options(
            entry,
            {
                "entities": {
                    "front_door_0": {
                        "device_class": "battery",
                        "unit_of_measurement": "%",
                    },
                    "front_door_1": sibling,
                }
            },
        )
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu2")
        coord = coordinator(hass, entry, [clu])
        device = DeviceMapper.to_domain(widget_factory(), coord)
        entry.runtime_data = RuntimeData(coord, [device])
        platforms = await register_platforms(hass, entry)
        original_id = device.entities[0].entity_id
        manager = configure_manager(hass, entry)
        form = await manager.async_init(entry.entry_id)
        form = await manager.async_configure(
            form["flow_id"], {"next_step_id": "entity_list"}
        )
        form = await manager.async_configure(form["flow_id"], {"entity": original_id})
        form = await manager.async_configure(form["flow_id"], {"entity_type": "sensor"})
        form = await manager.async_configure(form["flow_id"], {"device_class": "none"})
        assert form["step_id"] == "configure_sensor_unit"
        unit_field = fields(form)["unit_of_measurement"]
        assert unit_field["default"] == "%"
        assert unit_field["selector"]["select"]["custom_value"]
        result = await manager.async_configure(
            form["flow_id"], {"unit_of_measurement": unit}
        )
        assert result["type"] == "create_entry"
        config = entry.options["entities"][device.entities[0].unique_id]
        assert "device_class" not in config
        assert config.get("unit_of_measurement") == expected
        assert entry.options["entities"]["front_door_1"] == sibling
        for platform in platforms:
            await platform.async_reset()

        restored = coordinator(hass, entry, [clu])
        device = DeviceMapper.to_domain(widget_factory(), restored)
        entry.runtime_data = RuntimeData(restored, [device])
        entity = device.entities[0]
        await restored._process_report(
            clu.id, [restored._state_key(entity.state_object)], [96]
        )
        platforms = await register_platforms(hass, entry)
        assert entity.entity_id == original_id
        state = hass.states.get(entity.entity_id)
        assert float(state.state) == 96
        assert "device_class" not in state.attributes
        assert state.attributes.get("unit_of_measurement") == expected
        assert state.attributes["state_class"] == "measurement"
        # Reopening uses the saved custom unit (or the explicit unitless choice).
        form = entity._get_schema_instance()._build_step_unit_schema(config, {})
        assert fields({"data_schema": form.schema})["unit_of_measurement"][
            "default"
        ] == (expected or "none")
        for platform in platforms:
            await platform.async_reset()
        await coord.async_shutdown()
        await restored.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("grenton_type", ["INTEGER", "FLOAT"])
@pytest.mark.parametrize(
    "unit, expected", [("%", "%"), ("turns", "turns"), ("none", None)]
)
def test_generic_clu_variable_unit_saved_without_device_class(
    tmp_path, grenton_type, unit, expected
):
    async def run():
        entry = variable_entry()
        other = {"variable_name": "Other", "label": "Other", "grenton_type": "INTEGER"}
        set_options(entry, {"clu_variables": {"clu2": {"other": other}}})
        hass = await make_hass(tmp_path, [entry])
        manager = configure_manager(hass, entry)
        form = await open_clu_variables(manager, entry)
        form = await manager.async_configure(form["flow_id"], {"operation": "add"})
        form = await manager.async_configure(
            form["flow_id"], {"variable_name": "Opening", "grenton_type": grenton_type}
        )
        form = await manager.async_configure(form["flow_id"], {"device_class": "none"})
        assert form["step_id"] == "configure_sensor_unit"
        assert fields(form)["unit_of_measurement"]["default"] == "none"
        await manager.async_configure(form["flow_id"], {"unit_of_measurement": unit})
        config = next(iter(entry.options["clu_variables"]["clu1"].values()))
        assert "device_class" not in config
        assert config.get("unit_of_measurement") == expected
        assert entry.options["clu_variables"]["clu2"] == {"other": other}
        clu = make_clu("clu1")
        coord = coordinator(hass, entry, [clu])
        entity = custom_variable_entities(coord, clu)[0]
        entry.runtime_data = RuntimeData(coord, [], [entity])
        await coord._process_report(
            clu.id, [coord._state_key(entity.state_object)], [96]
        )
        platforms = await register_platforms(hass, entry)
        state = hass.states.get(entity.entity_id)
        assert float(state.state) == 96
        assert state.attributes.get("unit_of_measurement") == expected
        assert "device_class" not in state.attributes
        for platform in platforms:
            await platform.async_reset()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_classified_sensor_rejects_custom_units_after_generic_sensor(tmp_path):
    async def run():
        entry = make_entry()
        set_options(
            entry, {"entities": {"front_door_0": {"unit_of_measurement": "steps"}}}
        )
        hass = await make_hass(tmp_path, [entry])
        coord = coordinator(hass, entry, [make_clu("clu2")])
        device = DeviceMapper.to_domain(widget(), coord)
        entry.runtime_data = RuntimeData(coord, [device])
        device.entities[0].entity_id = "sensor.opening"
        manager = configure_manager(hass, entry)
        form = await manager.async_init(entry.entry_id)
        form = await manager.async_configure(
            form["flow_id"], {"next_step_id": "entity_list"}
        )
        form = await manager.async_configure(
            form["flow_id"], {"entity": "sensor.opening"}
        )
        form = await manager.async_configure(form["flow_id"], {"entity_type": "sensor"})
        form = await manager.async_configure(
            form["flow_id"], {"device_class": "temperature"}
        )
        field = fields(form)["unit_of_measurement"]
        assert not field["selector"]["select"]["custom_value"]
        assert field["default"] in field["selector"]["select"]["options"]
        with pytest.raises(InvalidData):
            await manager.async_configure(form["flow_id"], {"unit_of_measurement": "%"})
        assert (
            entry.options["entities"]["front_door_0"]["unit_of_measurement"] == "steps"
        )
        await manager.async_configure(form["flow_id"], {"unit_of_measurement": "°C"})
        assert entry.options["entities"]["front_door_0"]["unit_of_measurement"] == "°C"
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())
