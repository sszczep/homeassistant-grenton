"""Native options flows and entity lifecycle for user-selected CLU variables."""

import asyncio
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import OptionsFlowManager
from homeassistant.data_entry_flow import InvalidData
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from test_clu_scripts import make_clu, make_entry, make_hass
from test_clu_state import coordinator, register_platforms
from test_integration_configuration import fields

from custom_components.homeassistant_grenton import _cleanup_orphans
from custom_components.homeassistant_grenton.domain.api.clu_messages.action import (
    GrentonCluApiActionRequest,
)
from custom_components.homeassistant_grenton.domain.api.clu_messages.client_register import (
    GrentonCluApiClientRegisterRequest,
)
from custom_components.homeassistant_grenton.domain.entities.clu_state import (
    clu_entities,
)
from custom_components.homeassistant_grenton.domain.entities.clu_variables import (
    GrentonCluVariableSensor,
    GrentonCluVariableSwitch,
    custom_variable_entities,
)
from custom_components.homeassistant_grenton.integration_config import RuntimeData
from custom_components.homeassistant_grenton.options_flow import GrentonOptionsFlow


def set_options(entry, options):
    object.__setattr__(entry, "options", MappingProxyType(options))


def configure_manager(hass, entry):
    manager = OptionsFlowManager(hass)
    manager.async_create_flow = AsyncMock(
        side_effect=lambda *args, **kwargs: GrentonOptionsFlow()
    )
    hass.config_entries.options = manager
    hass.config_entries.async_get_known_entry = lambda entry_id: entry

    def update(current, *, options):
        set_options(current, options)
        return True

    hass.config_entries.async_update_entry = Mock(side_effect=update)
    hass.config_entries.async_schedule_reload = Mock()
    return manager


async def open_clu_variables(manager, entry):
    """Manage variables directly through Configure CLU."""
    form = await manager.async_init(entry.entry_id)
    form = await manager.async_configure(
        form["flow_id"], {"next_step_id": "clu_read_settings"}
    )
    form = await manager.async_configure(form["flow_id"], {"clu_id": "clu1"})
    assert form["step_id"] == "clu_configuration"
    assert form["menu_options"] == ["clu_read_interval", "clu_variables"]
    return await manager.async_configure(
        form["flow_id"], {"next_step_id": "clu_variables"}
    )


def variable_entry():
    return make_entry(
        interface={
            "clus": [{"id": "clu1", "name": "Main"}, {"id": "clu2", "name": "Other"}]
        }
    )


def test_native_clu_add_edit_remove_and_cancel_preserve_other_options(tmp_path):
    async def run():
        entry = variable_entry()
        other = {
            "variable_name": "Enabled",
            "label": "Other",
            "grenton_type": "BOOLEAN",
        }
        set_options(
            entry,
            {
                "entities": {"widget_0": {"device_class": "temperature"}},
                "clu_variables": {"clu2": {"other": other}},
            },
        )
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu1")
        coord = coordinator(hass, entry, [clu])
        controllers = clu_entities(coord, clu)
        entry.runtime_data = RuntimeData(coord, [], controllers)
        controllers[0].entity_id = "sensor.main_controller"
        controllers[0]._attr_name = "Controller"
        coord._apis[clu.id].execute_action = AsyncMock()
        manager = configure_manager(hass, entry)
        initial = await open_clu_variables(manager, entry)
        assert initial["step_id"] == "clu_variables"
        form = await manager.async_configure(initial["flow_id"], {"operation": "add"})
        assert "text" in fields(form)["variable_name"]["selector"]
        assert not fields(form)["label"]["required"]
        result = await manager.async_configure(
            form["flow_id"],
            {
                "variable_name": " Enabled ",
                "label": "Office enabled",
                "grenton_type": "BOOLEAN",
            },
        )
        assert result["type"] == "create_entry"
        variables = entry.options["clu_variables"]["clu1"]
        variable_id = next(iter(variables))
        assert variables[variable_id] == {
            "variable_name": "Enabled",
            "label": "Office enabled",
            "grenton_type": "BOOLEAN",
            "read_mode": "realtime",
        }
        assert entry.options["clu_variables"]["clu2"] == {"other": other}
        assert entry.options["entities"] == {
            "widget_0": {"device_class": "temperature"}
        }
        hass.config_entries.async_schedule_reload.assert_called_once_with(
            entry.entry_id
        )

        # Cancelling a partially completed add changes no options or subscriptions.
        snapshot = dict(entry.options)
        flow = await open_clu_variables(manager, entry)
        flow = await manager.async_configure(flow["flow_id"], {"operation": "add"})
        flow = await manager.async_configure(
            flow["flow_id"],
            {"variable_name": "OfficeTemperature", "grenton_type": "FLOAT"},
        )
        assert flow["step_id"] == "configure_sensor_class"
        manager.async_abort(flow["flow_id"])
        assert entry.options == snapshot
        assert coord.state.clus[clu.id].get_subscription_order() == []

        # Editing changes the type/name while retaining its persisted identity.
        flow = await open_clu_variables(manager, entry)
        flow = await manager.async_configure(flow["flow_id"], {"operation": "edit"})
        flow = await manager.async_configure(
            flow["flow_id"], {"variable_id": variable_id}
        )
        assert fields(flow)["variable_name"]["default"] == "Enabled"
        flow = await manager.async_configure(
            flow["flow_id"],
            {
                "variable_name": "OfficeTemperature",
                "label": "Office temperature",
                "grenton_type": "FLOAT",
                "read_mode": "slow",
            },
        )
        flow = await manager.async_configure(
            flow["flow_id"], {"device_class": "temperature"}
        )
        assert flow["step_id"] == "configure_sensor_unit"
        result = await manager.async_configure(
            flow["flow_id"], {"unit_of_measurement": "°C"}
        )
        assert result["type"] == "create_entry"
        assert set(entry.options["clu_variables"]["clu1"]) == {variable_id}
        assert (
            entry.options["clu_variables"]["clu1"][variable_id]["read_mode"] == "slow"
        )
        assert (
            entry.options["clu_variables"]["clu1"][variable_id]["device_class"]
            == "temperature"
        )
        assert (
            entry.options["clu_variables"]["clu1"][variable_id]["unit_of_measurement"]
            == "°C"
        )

        # No class/unit is required for string and plain numeric variables.
        for variable_name, grenton_type in [
            ("Status", "STRING"),
            ("Counter", "INTEGER"),
        ]:
            flow = await open_clu_variables(manager, entry)
            flow = await manager.async_configure(flow["flow_id"], {"operation": "add"})
            flow = await manager.async_configure(
                flow["flow_id"],
                {"variable_name": variable_name, "grenton_type": grenton_type},
            )
            flow = await manager.async_configure(
                flow["flow_id"], {"device_class": "none"}
            )
            assert flow["step_id"] == "configure_sensor_unit"
            result = await manager.async_configure(flow["flow_id"], {})
            assert result["type"] == "create_entry"
            assert not any(
                "unit_of_measurement" in config
                for config in entry.options["clu_variables"]["clu1"].values()
                if config["variable_name"] == variable_name
            )

        flow = await open_clu_variables(manager, entry)
        flow = await manager.async_configure(flow["flow_id"], {"operation": "remove"})
        assert flow["step_id"] == "clu_variable_remove"
        result = await manager.async_configure(
            flow["flow_id"], {"variable_id": variable_id}
        )
        assert result["type"] == "create_entry"
        assert variable_id not in entry.options["clu_variables"]["clu1"]
        assert entry.options["clu_variables"]["clu2"] == {"other": other}
        coord._apis[clu.id].execute_action.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("grenton_type", ["BOOLEAN", "STRING", "INTEGER", "FLOAT"])
@pytest.mark.parametrize("read_mode", [None, "realtime", "slow"])
@pytest.mark.parametrize("http_gate", [False, True])
def test_variable_read_policy_on_load_and_stale_polled_values(
    tmp_path, grenton_type, read_mode, http_gate
):
    async def run():
        entry = variable_entry()
        config = {
            "variable_name": "Value",
            "label": "Value",
            "grenton_type": grenton_type,
        }
        if read_mode is not None:
            config["read_mode"] = read_mode
        set_options(entry, {"clu_variables": {"clu1": {"value": config}}})
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu1")
        clu.serial_number = "521000921" if http_gate else "221000921"
        coord = coordinator(hass, entry, [clu])
        entity = custom_variable_entities(coord, clu)[0]
        key = coord._state_key(entity.state_object)
        slow = read_mode == "slow" or http_gate
        assert coord.state_read_mode(entity.state_object) == (
            "slow" if slow else "realtime"
        )
        assert (key in coord._slow_keys[clu.id]) == slow
        assert (key in coord._realtime_keys[clu.id]) != slow
        api = coord._apis[clu.id]
        value = (
            True
            if grenton_type == "BOOLEAN"
            else "ok"
            if grenton_type == "STRING"
            else 21
        )
        api.poll_component_states = AsyncMock(return_value=[value])
        api.register_component_states = AsyncMock(return_value=[value])
        await coord.async_refresh_clu_state(clu.id)
        assert entity.available
        if slow:
            api.poll_component_states.assert_awaited_once_with([key])
            api.register_component_states.assert_not_awaited()
            if grenton_type == "BOOLEAN":
                api.execute_action = AsyncMock(return_value=True)
                api.poll_component_states.reset_mock(return_value=True)
                api.poll_component_states.return_value = [False]
                await entity.async_turn_off()
                api.poll_component_states.assert_awaited_once_with([key])
                api.register_component_states.assert_not_awaited()
                assert not entity.is_on
            stamp = coord._slow_success[clu.id][key][0]
            with patch(
                "custom_components.homeassistant_grenton.coordinator.monotonic",
                return_value=stamp + 121,
            ):
                assert not entity.available
        else:
            api.register_component_states.assert_awaited_once_with([key])
            api.poll_component_states.assert_not_awaited()
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


def test_manage_variables_without_runtime_or_controller_entity(tmp_path):
    async def run():
        entry = variable_entry()
        original = {"clu_read_settings": {"clu2": {"slow_read_interval": 5}}}
        set_options(entry, original)
        hass = await make_hass(tmp_path, [entry])
        manager = configure_manager(hass, entry)
        form = await open_clu_variables(manager, entry)
        form = await manager.async_configure(form["flow_id"], {"operation": "add"})
        assert fields(form)["read_mode"]["default"] == "realtime"
        result = await manager.async_configure(
            form["flow_id"],
            {
                "variable_name": "Enabled",
                "grenton_type": "BOOLEAN",
                "read_mode": "slow",
            },
        )
        assert result["type"] == "create_entry"
        variable_id, config = next(iter(entry.options["clu_variables"]["clu1"].items()))
        assert config["read_mode"] == "slow"
        form = await open_clu_variables(manager, entry)
        form = await manager.async_configure(form["flow_id"], {"operation": "edit"})
        form = await manager.async_configure(
            form["flow_id"], {"variable_id": variable_id}
        )
        assert fields(form)["read_mode"]["default"] == "slow"
        await manager.async_configure(
            form["flow_id"],
            {
                "variable_name": "Enabled",
                "grenton_type": "BOOLEAN",
                "read_mode": "realtime",
            },
        )
        assert (
            entry.options["clu_variables"]["clu1"][variable_id]["read_mode"]
            == "realtime"
        )
        form = await open_clu_variables(manager, entry)
        form = await manager.async_configure(form["flow_id"], {"operation": "remove"})
        result = await manager.async_configure(
            form["flow_id"], {"variable_id": variable_id}
        )
        assert result["type"] == "create_entry"
        assert entry.options == {**original, "clu_variables": {"clu1": {}}}
        hass.config_entries.async_schedule_reload.assert_called_with(entry.entry_id)
        await hass.async_stop()

    asyncio.run(run())


def test_flow_validates_names_types_scope_and_unit_without_saving(tmp_path):
    async def run():
        entry = variable_entry()
        set_options(
            entry,
            {
                "clu_variables": {
                    "clu1": {
                        "first": {
                            "variable_name": "Existing",
                            "label": "Existing",
                            "grenton_type": "BOOLEAN",
                        }
                    }
                }
            },
        )
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu1")
        coord = coordinator(hass, entry, [clu])
        entry.runtime_data = RuntimeData(coord, [], clu_entities(coord, clu))
        manager = configure_manager(hass, entry)
        entry.runtime_data.clu_entities[0].entity_id = "sensor.main_controller"
        form = await manager.async_init(entry.entry_id)
        form = await manager.async_configure(
            form["flow_id"], {"next_step_id": "clu_read_settings"}
        )
        with pytest.raises(InvalidData):
            await manager.async_configure(
                form["flow_id"], {"clu_id": "missing_controller"}
            )
        manager.async_abort(form["flow_id"])
        flow = await open_clu_variables(manager, entry)
        flow = await manager.async_configure(flow["flow_id"], {"operation": "add"})
        for name in (" ", "Existing"):
            flow = await manager.async_configure(
                flow["flow_id"], {"variable_name": name, "grenton_type": "BOOLEAN"}
            )
            assert flow["errors"] == {"variable_name": "invalid_configuration"}
        with pytest.raises(InvalidData):
            await manager.async_configure(
                flow["flow_id"], {"variable_name": "New", "grenton_type": "METHOD"}
            )
        with pytest.raises(InvalidData):
            await manager.async_configure(
                flow["flow_id"],
                {"variable_name": "New", "grenton_type": "FLOAT", "read_mode": "fast"},
            )
        flow = await manager.async_configure(
            flow["flow_id"], {"variable_name": "New", "grenton_type": "FLOAT"}
        )
        flow = await manager.async_configure(
            flow["flow_id"], {"device_class": "temperature"}
        )
        with pytest.raises(InvalidData):
            await manager.async_configure(flow["flow_id"], {"unit_of_measurement": "W"})
        manager.async_abort(flow["flow_id"])
        assert set(entry.options["clu_variables"]["clu1"]) == {"first"}
        hass.config_entries.async_schedule_reload.assert_not_called()

    asyncio.run(run())


def test_native_entities_share_clu_device_and_switch_writes_only_own_variable(tmp_path):
    async def run():
        entry = variable_entry()
        configs = {
            "enabled": {
                "variable_name": "Enabled",
                "label": "Enabled",
                "grenton_type": "BOOLEAN",
            },
            "temperature": {
                "variable_name": "Temperature",
                "label": "Temperature",
                "grenton_type": "FLOAT",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
            },
            "count": {
                "variable_name": "Count",
                "label": "Count",
                "grenton_type": "INTEGER",
            },
            "status": {
                "variable_name": "Status",
                "label": "Status",
                "grenton_type": "STRING",
            },
        }
        set_options(
            entry,
            {
                "clu_variables": {
                    "clu1": configs,
                    "clu2": {"enabled": configs["enabled"]},
                }
            },
        )
        hass = await make_hass(tmp_path, [entry])
        clus = [make_clu("clu1"), make_clu("clu2", "Second")]
        coord = coordinator(hass, entry, clus)
        entities = [entity for clu in clus for entity in clu_entities(coord, clu)]
        entry.runtime_data = RuntimeData(coord, [], entities)
        keys = coord.state.clus["clu1"].get_subscription_order()
        assert (
            GrentonCluApiClientRegisterRequest(keys, 0).payload
            == 'SYSTEM:clientRegister(0,0,1,{"Enabled","Temperature","Count","Status"})'
        )
        platforms = await register_platforms(hass, entry)
        for entity in entities:
            if isinstance(entity, GrentonCluVariableSwitch) or (
                isinstance(entity, GrentonCluVariableSensor)
                and entity.value_type.value != "STRING"
            ):
                assert hass.states.get(entity.entity_id).state == "unknown"
        await coord._process_report("clu1", keys, [False, 21.5, 42, "Working"])
        await coord._process_report(
            "clu2", coord.state.clus["clu2"].get_subscription_order(), [True]
        )
        assert [len(platform.entities) for platform in platforms] == [9, 2, 2]
        switches = [
            entity
            for entity in entities
            if isinstance(entity, GrentonCluVariableSwitch)
        ]
        sensors = [
            entity
            for entity in entities
            if isinstance(entity, GrentonCluVariableSensor)
        ]
        assert hass.states.get(switches[0].entity_id).state == "off"
        assert hass.states.get(switches[1].entity_id).state == "on"
        assert [hass.states.get(entity.entity_id).state for entity in sensors] == [
            "21.5",
            "42",
            "Working",
        ]
        assert sensors[0].device_class.value == "temperature"
        assert sensors[0].native_unit_of_measurement == "°C"
        assert sensors[0].state_class.value == "measurement"
        assert sensors[2].state_class is None
        for sensor in sensors:
            attributes = hass.states.get(sensor.entity_id).attributes
            assert {
                key: attributes[key] for key in ("call_type", "clu_id", "object")
            } == {
                "call_type": "VARIABLE",
                "clu_id": "clu1",
                "object": sensor.state_object.index,
            }
            assert "state_source" not in attributes
            assert "variable_name" not in attributes
            assert attributes["grenton_type"] == sensor.value_type.value
        await coord._process_report(
            "clu1", keys, [False, "not a number", "invalid", "Working"]
        )
        assert hass.states.get(sensors[0].entity_id).state == "unknown"
        assert hass.states.get(sensors[1].entity_id).state == "unknown"
        await coord._process_report("clu1", keys, [False, 21.5, 42, "Working"])
        assert hass.states.get(switches[0].entity_id).attributes["object"] == "Enabled"
        for clu in clus:
            group = [entity for entity in entities if entity.clu.id == clu.id]
            assert len({entity.registry_entry.device_id for entity in group}) == 1
        assert len(dr.async_get(hass).devices) == 2
        api = SimpleNamespace(
            execute_action=AsyncMock(return_value=True),
            register_component_states=AsyncMock(
                return_value=[False, 21.5, 42, "Working"]
            ),
            state_read_batches=coord._apis["clu1"].state_read_batches,
            subscription_count=0,
        )
        coord._apis["clu1"] = api
        await switches[0].async_turn_on()
        action = api.execute_action.await_args.args[0]
        assert action.clu_id == "clu1"
        assert (
            GrentonCluApiActionRequest.from_action(action).payload
            == 'setVar("Enabled",true)'
        )
        assert switches[0].is_on is False
        api.register_component_states.return_value = [True, 21.5, 42, "Working"]
        await switches[0].async_turn_on()
        assert switches[0].is_on is True
        await switches[0].async_turn_off()
        assert (
            GrentonCluApiActionRequest.from_action(
                api.execute_action.await_args.args[0]
            ).payload
            == 'setVar("Enabled",false)'
        )

        api.execute_action.return_value = False
        api.register_component_states.reset_mock()
        with pytest.raises(HomeAssistantError, match="rejected"):
            await switches[0].async_turn_off()
        api.register_component_states.assert_not_awaited()

        # Domain changes remove the old registry row; reload keeps sibling IDs.
        old_switch_id = switches[0].entity_id
        uid = switches[0].unique_id
        sibling_ids = {sensor.entity_id for sensor in sensors}
        old_device_id = switches[0].registry_entry.device_id
        for platform in platforms:
            await platform.async_reset()
        updated = dict(configs)
        updated["enabled"] = {**configs["enabled"], "grenton_type": "STRING"}
        set_options(
            entry,
            {
                "clu_variables": {
                    "clu1": updated,
                    "clu2": {"enabled": configs["enabled"]},
                }
            },
        )
        replacement = [entity for clu in clus for entity in clu_entities(coord, clu)]
        _cleanup_orphans(hass, entry, [], replacement)
        assert er.async_get(hass).async_get(old_switch_id) is None
        entry.runtime_data.clu_entities = replacement
        platforms = await register_platforms(hass, entry)
        changed = next(entity for entity in replacement if entity.unique_id == uid)
        assert changed.entity_id.startswith("sensor.")
        assert changed.registry_entry.device_id == old_device_id
        assert {
            entity.entity_id
            for entity in replacement
            if entity.unique_id.endswith(("_temperature", "_count", "_status"))
        } == sibling_ids
        for platform in platforms:
            await platform.async_reset()
        removed_id = changed.entity_id
        updated.pop("enabled")
        set_options(
            entry,
            {
                "clu_variables": {
                    "clu1": updated,
                    "clu2": {"enabled": configs["enabled"]},
                }
            },
        )
        refreshed = coordinator(hass, entry, clus)
        kept = [entity for clu in clus for entity in clu_entities(refreshed, clu)]
        assert [
            key.name for key in refreshed.state.clus["clu1"].get_subscription_order()
        ] == ["Temperature", "Count", "Status"]
        _cleanup_orphans(hass, entry, [], kept)
        assert er.async_get(hass).async_get(removed_id) is None
        assert all(er.async_get(hass).async_get(entity_id) for entity_id in sibling_ids)
        assert len(dr.async_get(hass).devices) == 2

    asyncio.run(run())


def test_integration_entity_editor_uses_same_variable_schema_and_persistence(tmp_path):
    async def run():
        entry = variable_entry()
        config = {
            "variable_name": "Counter",
            "label": "Counter",
            "grenton_type": "INTEGER",
            "device_class": "duration",
            "unit_of_measurement": "s",
            "read_mode": "slow",
        }
        set_options(
            entry,
            {
                "entities": {"widget_0": {"keep": True}},
                "clu_variables": {"clu1": {"counter": config}},
            },
        )
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu1")
        coord = coordinator(hass, entry, [clu])
        entities = clu_entities(coord, clu)
        entry.runtime_data = RuntimeData(coord, [], entities)
        platforms = await register_platforms(hass, entry)
        manager = configure_manager(hass, entry)
        controller, counter = entities[0], entities[-1]
        form = await manager.async_init(entry.entry_id)
        form = await manager.async_configure(
            form["flow_id"], {"next_step_id": "entity_list"}
        )
        choices = fields(form)["entity"]["selector"]["grenton_entity"][
            "include_entities"
        ]
        assert set(choices) == {counter.entity_id}
        assert controller.entity_id not in choices
        form = await manager.async_configure(
            form["flow_id"], {"entity": counter.entity_id}
        )
        assert form["step_id"] == "configure_clu_variable"
        assert fields(form)["grenton_type"]["default"] == "INTEGER"
        assert fields(form)["read_mode"]["default"] == "slow"
        result = await manager.async_configure(
            form["flow_id"],
            {"variable_name": "Enabled", "label": "Enabled", "grenton_type": "BOOLEAN"},
        )
        assert result["type"] == "create_entry"
        assert entry.options["clu_variables"]["clu1"]["counter"] == {
            "variable_name": "Enabled",
            "label": "Enabled",
            "grenton_type": "BOOLEAN",
            "read_mode": "slow",
        }
        assert entry.options["entities"] == {"widget_0": {"keep": True}}
        hass.config_entries.async_schedule_reload.assert_called_once_with(
            entry.entry_id
        )
        refreshed = coordinator(hass, entry, [clu])
        replacement = clu_entities(refreshed, clu)
        assert replacement[-1].unique_id == counter.unique_id
        assert isinstance(replacement[-1], GrentonCluVariableSwitch)
        assert [
            key.name for key in refreshed.state.clus[clu.id].get_subscription_order()
        ] == ["Enabled"]
        form = await open_clu_variables(manager, entry)
        assert form["step_id"] == "clu_variables"
        manager.async_abort(form["flow_id"])
        for platform in platforms:
            await platform.async_reset()

    asyncio.run(run())
