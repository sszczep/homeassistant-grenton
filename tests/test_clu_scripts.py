"""CLU discovery, Home Assistant targeting, script arguments and reloads."""

import asyncio
import json
import logging
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import yaml
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.entity_platform import EntityPlatform
from probatio import Invalid, Schema

from custom_components.homeassistant_grenton import (
    _cleanup_orphans,
    async_setup,
    async_setup_entry,
)
from custom_components.homeassistant_grenton.coordinator import GrentonCoordinator
from custom_components.homeassistant_grenton.domain.api.clu_messages.action import (
    GrentonCluApiActionRequest,
)
from custom_components.homeassistant_grenton.domain.clu import GrentonClu
from custom_components.homeassistant_grenton.domain.entities.clu import GrentonCluEntity
from custom_components.homeassistant_grenton.domain.scene_arguments import (
    arguments_to_ui,
)
from custom_components.homeassistant_grenton.integration_config import RuntimeData
from custom_components.homeassistant_grenton.sensor import (
    async_setup_entry as setup_sensors,
)
from custom_components.homeassistant_grenton.services import SERVICE_RUN_SCRIPT_SCHEMA


def make_entry(entry_id="interface1", interface=None):
    return ConfigEntry(
        domain="grenton",
        entry_id=entry_id,
        title=entry_id,
        data={"interface": interface} if interface else {},
        options={},
        source="user",
        unique_id=entry_id,
        version=1,
        minor_version=1,
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
    )


def make_coordinator(entry, clus):
    return SimpleNamespace(
        config_entry=entry,
        clus=clus,
        last_update_success=True,
        async_add_listener=Mock(return_value=Mock()),
        async_setup=AsyncMock(),
        execute_action=AsyncMock(),
        register_component_state=Mock(),
        get_value_for_component=Mock(return_value=None),
        states_available=Mock(return_value=True),
    )


def make_clu(clu_id, name="Main CLU"):
    return GrentonClu(clu_id, f"serial-{clu_id}", name, "192.0.2.1", 1234)


async def make_hass(tmp_path, entries):
    hass = HomeAssistant(str(tmp_path))
    by_id = {entry.entry_id: entry for entry in entries}
    hass.config_entries = SimpleNamespace(
        async_get_entry=by_id.get,
        async_entries=lambda *args, **kwargs: list(by_id.values()),
    )
    dr.async_setup(hass)
    await asyncio.gather(
        dr.async_load(hass, load_empty=True), er.async_load(hass, load_empty=True)
    )
    return hass


async def add_controllers(hass, entry, clus):
    coordinator = make_coordinator(entry, clus)
    controllers = [GrentonCluEntity(coordinator, clu) for clu in clus]
    entry.runtime_data = RuntimeData(coordinator, [], controllers)
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
    # Use the integration's actual English names without loading unrelated HA
    # components. Entity/device registration and service routing remain real.
    translations = {"component.grenton.entity.sensor.clu_controller.name": "Controller"}
    platform.platform_data.platform_translations = translations
    platform.platform_data.object_id_platform_translations = translations
    platform.platform_data.default_language_platform_translations = translations
    collected = Mock()
    await setup_sensors(hass, entry, collected)
    await platform.async_add_entities(collected.call_args.args[0])
    assert len(platform.entities) == len(clus)
    return coordinator, controllers, platform


def test_discovered_clu_devices_and_real_entity_device_target_routing(tmp_path):
    async def run():
        entry1, entry2 = make_entry(), make_entry("interface2")
        hass = await make_hass(tmp_path, [entry1, entry2])
        assert await async_setup(hass, {})
        assert hass.services.has_service("grenton", "run_script")
        assert hass.services.has_service("grenton", "run_scene")
        coordinator1, controllers1, platform1 = await add_controllers(
            hass, entry1, [make_clu("clu1"), make_clu("clu2", "Upstairs CLU")]
        )
        coordinator2, controllers2, platform2 = await add_controllers(
            hass, entry2, [make_clu("clu3", "Other installation")]
        )
        entity = controllers1[1]
        state = hass.states.get(entity.entity_id)
        assert state.state == "serial-clu2"
        assert state.attributes["clu_id"] == "clu2"
        assert state.attributes["ip"] == "192.0.2.1"
        assert state.attributes["port"] == 1234
        device = dr.async_get(hass).async_get(entity.registry_entry.device_id)
        assert device.name == "Upstairs CLU"
        assert device.model == "CLU"
        assert device.serial_number == "serial-clu2"
        await hass.services.async_call(
            "grenton",
            "run_script",
            {
                "script": "Evening",
                "arguments": arguments_to_ui(
                    [
                        {"type": "string", "value": 'room "A"'},
                        {"type": "number", "value": 0},
                        {"type": "float", "value": 0.75},
                        {"type": "boolean", "value": False},
                        {"type": "nil", "value": None},
                        {"type": "lua", "value": "other.value"},
                    ]
                ),
            },
            target={"entity_id": entity.entity_id},
            blocking=True,
        )
        action = coordinator1.execute_action.await_args.args[0]
        assert action.clu_id == "clu2"
        assert GrentonCluApiActionRequest.from_action(action).payload == (
            'Evening("room \\"A\\"", 0, 0.75, false, nil, other.value)'
        )
        assert coordinator1.execute_action.await_args.kwargs == {"raise_on_error": True}
        coordinator2.execute_action.assert_not_awaited()
        # A device target resolves its controller, not a scene widget.
        await hass.services.async_call(
            "grenton",
            "run_script",
            {"script": "UseDefaults"},
            target={"device_id": controllers2[0].registry_entry.device_id},
            blocking=True,
        )
        action = coordinator2.execute_action.await_args.args[0]
        assert action.clu_id == "clu3"
        assert GrentonCluApiActionRequest.from_action(action).payload == "UseDefaults()"
        # Multiple entity targets call the script separately on each CLU.
        coordinator1.execute_action.reset_mock()
        await hass.services.async_call(
            "grenton",
            "run_script",
            {"script": "AnotherScript", "arguments": []},
            target={"entity_id": [entity.entity_id for entity in controllers1]},
            blocking=True,
        )
        assert {
            call.args[0].clu_id for call in coordinator1.execute_action.await_args_list
        } == {"clu1", "clu2"}
        assert entry1.options == {}
        # Ordinary widget sensors cannot be used as a CLU target.
        ordinary_sensor = SensorEntity()
        ordinary_sensor.entity_id = "sensor.room_value"
        ordinary_sensor._attr_native_value = 25
        await platform1.async_add_entities([ordinary_sensor])
        coordinator1.execute_action.reset_mock()
        with pytest.raises(ServiceValidationError, match="CLU controller"):
            await hass.services.async_call(
                "grenton",
                "run_script",
                {"script": "Evening"},
                target={"entity_id": ordinary_sensor.entity_id},
                blocking=True,
            )
        coordinator1.execute_action.assert_not_awaited()
        # Platform unload removes live entities from service routing.
        await platform2.async_reset()
        coordinator2.execute_action.reset_mock()
        await hass.services.async_call(
            "grenton",
            "run_script",
            {"script": "AfterUnload"},
            target={"entity_id": controllers2[0].entity_id},
            blocking=True,
        )
        coordinator2.execute_action.assert_not_awaited()
        await platform1.async_reset()

    asyncio.run(run())


def test_clu_reconfiguration_preserves_identity_and_removes_only_orphans(tmp_path):
    async def run():
        entry1, entry2 = make_entry(), make_entry("interface2")
        hass = await make_hass(tmp_path, [entry1, entry2])
        _, controllers1, platform1 = await add_controllers(
            hass, entry1, [make_clu("clu1"), make_clu("removed", "Removed CLU")]
        )
        _, controllers2, platform2 = await add_controllers(
            hass, entry2, [make_clu("other", "Other installation")]
        )
        entity_registry = er.async_get(hass)
        kept = controllers1[0]
        kept_entity_id, kept_device_id = kept.entity_id, kept.registry_entry.device_id
        removed_entity_id = controllers1[1].entity_id
        removed_device_id = controllers1[1].registry_entry.device_id
        entity_registry.async_update_entity(kept_entity_id, name="My controller")
        await platform1.async_reset()
        replacement = make_clu("clu1", "Renamed CLU")
        replacement.ip = "192.0.2.99"
        new_coordinator = make_coordinator(entry1, [replacement])
        new_entities = [GrentonCluEntity(new_coordinator, replacement)]
        _cleanup_orphans(hass, entry1, [], new_entities)
        assert entity_registry.async_get(kept_entity_id).name == "My controller"
        assert entity_registry.async_get(removed_entity_id) is None
        assert dr.async_get(hass).async_get(removed_device_id) is None
        assert entity_registry.async_get(controllers2[0].entity_id) is not None
        coordinator, reloaded, reloaded_platform = await add_controllers(
            hass, entry1, [replacement]
        )
        assert reloaded[0].entity_id == kept_entity_id
        assert reloaded[0].registry_entry.device_id == kept_device_id
        assert hass.states.get(kept_entity_id).attributes["ip"] == "192.0.2.99"
        await async_setup(hass, {})
        await hass.services.async_call(
            "grenton",
            "run_script",
            {"script": "AfterReload"},
            target={"entity_id": kept_entity_id},
            blocking=True,
        )
        assert coordinator.execute_action.await_args.args[0].clu_id == "clu1"
        await reloaded_platform.async_reset()
        await platform2.async_reset()

    asyncio.run(run())


@pytest.mark.parametrize("failure", [False, OSError("network failure"), None])
def test_script_action_reports_transport_failures(failure):
    async def run():
        coordinator = GrentonCoordinator.__new__(GrentonCoordinator)
        coordinator._stopping = False
        coordinator._publish_clu_update = Mock()
        api = SimpleNamespace(execute_action=AsyncMock(return_value=failure))
        if isinstance(failure, Exception):
            api.execute_action.side_effect = failure
        coordinator._apis = {} if failure is None else {"clu1": api}
        entity = GrentonCluEntity(coordinator, make_clu("clu1"))
        with pytest.raises(HomeAssistantError, match="CLU clu1"):
            await entity.async_run_script("Evening", [])

    asyncio.run(run())


def test_setup_discovers_all_imported_clus_without_any_widgets(tmp_path):
    interface = {
        "id": "interface1",
        "version": 1,
        "name": "Home",
        "icon": "home",
        "theme": "GRENTON",
        "encryption": {"key": "00" * 16, "iv": "00" * 16},
        "clus": [
            {
                "id": clu_id,
                "serialNumber": "221000001" if clu_id == "clu1" else "521000002",
                "name": clu_id,
                "ip": "192.0.2.1",
                "port": 1234,
                "connectionType": "LOCAL_ONLY",
            }
            for clu_id in ("clu1", "clu2")
        ],
        "pages": [],
        "pushNotifications": [],
    }

    async def run():
        hass = HomeAssistant(str(tmp_path))
        entry = make_entry(interface=interface)
        hass.config_entries = SimpleNamespace(async_forward_entry_setups=AsyncMock())
        coordinator = make_coordinator(entry, [])
        with (
            patch(
                "custom_components.homeassistant_grenton.GrentonCoordinator",
                return_value=coordinator,
            ),
            patch("custom_components.homeassistant_grenton._cleanup_orphans"),
        ):
            assert await async_setup_entry(hass, entry)
        assert entry.runtime_data.devices == []
        assert [entity.clu.id for entity in entry.runtime_data.clu_entities if isinstance(entity, GrentonCluEntity)] == [
            "clu1",
            "clu2",
        ]
        assert len(entry.runtime_data.clu_entities) == 17
        coordinator.async_setup.assert_awaited_once()
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"script": ""},
        {"script": "   "},
        {"script": 12},
        {"script": "Evening", "arguments": "1, 2"},
        {"script": "Evening", "arguments": [{"type": "float", "value": True}]},
    ],
)
def test_invalid_script_calls_are_rejected(data):
    with pytest.raises(Invalid):
        Schema(SERVICE_RUN_SCRIPT_SCHEMA)(data)


@pytest.mark.parametrize("language", ["en", "pl"])
def test_script_action_editor_and_translations(language):
    component = Path(__file__).parents[1] / "custom_components/homeassistant_grenton"
    services = yaml.safe_load((component / "services.yaml").read_text())
    assert set(services) == {"run_script", "run_scene", "set_thermostat_schedule"}
    metadata = services["run_script"]
    selector.TargetSelector(metadata["target"])
    arguments_selector = selector.selector(metadata["fields"]["arguments"]["selector"])
    registered_selector = next(
        value
        for key, value in SERVICE_RUN_SCRIPT_SCHEMA.items()
        if key.schema == "arguments"
    )
    assert arguments_selector.serialize() == registered_selector.serialize()
    assert arguments_selector([{"type": "float", "value": "0.75"}]) == [
        {"type": "float", "value": 0.75}
    ]
    translations = json.loads((component / f"translations/{language}.json").read_text())
    assert set(translations["services"]) == {"run_script", "run_scene", "set_thermostat_schedule"}
    assert set(translations["services"]["run_script"]["fields"]) == {
        "script",
        "arguments",
    }
    assert translations["entity"]["sensor"]["clu_controller"]["name"]


def test_upstream_run_scene_routes_real_ha_targets_without_changing_defaults(tmp_path):
    from copy import deepcopy

    from homeassistant.components.button import ButtonEntity

    from custom_components.homeassistant_grenton.domain.action import (
        GrentonActionScript,
    )
    from custom_components.homeassistant_grenton.domain.entities.scene_button import (
        GrentonEntitySceneButton,
    )
    from custom_components.homeassistant_grenton.domain.enums import (
        GrentonActionEventType,
    )

    async def run():
        entry1, entry2 = make_entry(), make_entry("interface2")
        hass = await make_hass(tmp_path, [entry1, entry2])
        await async_setup(hass, {})

        async def add_scene(entry, clu_id):
            coordinator = make_coordinator(entry, [make_clu(clu_id)])
            entity = GrentonEntitySceneButton(
                coordinator,
                f"scene_{clu_id}",
                f"Evening {clu_id}",
                GrentonActionScript(
                    clu_id=clu_id,
                    object_name="Evening",
                    event=GrentonActionEventType.CLICK,
                    value='42, "default"',
                ),
                device_info={"identifiers": {("grenton", f"scene_{clu_id}")}},
            )
            platform = EntityPlatform(
                hass=hass,
                logger=logging.getLogger(__name__),
                domain="button",
                platform_name="grenton",
                platform=None,
                scan_interval=timedelta(seconds=30),
                entity_namespace=None,
            )
            platform.config_entry = entry
            await platform.async_add_entities([entity])
            return coordinator, entity, platform

        coordinator1, scene1, platform1 = await add_scene(entry1, "clu1")
        coordinator2, scene2, platform2 = await add_scene(entry2, "clu2")
        saved = deepcopy(scene1._config)
        for data, expected in (
            ({}, 'Evening(42, "default")'),
            ({"parameter": '"abc"'}, 'Evening("abc")'),
            ({"parameter": "42"}, "Evening(42)"),
            (
                {"parameter": '"a,b", -1, OTHER:get(0)'},
                'Evening("a,b", -1, OTHER:get(0))',
            ),
            ({"parameter": ""}, "Evening()"),
        ):
            coordinator1.execute_action.reset_mock()
            await hass.services.async_call(
                "grenton",
                "run_scene",
                data,
                target={"entity_id": scene1.entity_id},
                blocking=True,
            )
            coordinator1.execute_action.assert_awaited_once()
            action = coordinator1.execute_action.await_args.args[0]
            assert GrentonCluApiActionRequest.from_action(action).payload == expected
            assert action.clu_id == "clu1"
            assert scene1._config == saved
            assert entry1.options == {}
            coordinator2.execute_action.assert_not_awaited()
        # A later button press still uses the saved scene arguments.
        await scene1.async_press()
        assert (
            GrentonCluApiActionRequest.from_action(
                coordinator1.execute_action.await_args.args[0]
            ).payload
            == 'Evening(42, "default")'
        )
        # Configured script targets and typed arguments also remain the default.
        await scene1.apply_configuration(
            {
                "call_type": "SCRIPT",
                "clu_id": "clu1",
                "object_name": "Configured",
                "arguments": [
                    {"type": "number", "value": -1},
                    {"type": "string", "value": "office"},
                ],
            }
        )
        saved = deepcopy(scene1._config)
        await hass.services.async_call(
            "grenton",
            "run_scene",
            {},
            target={"entity_id": scene1.entity_id},
            blocking=True,
        )
        assert (
            GrentonCluApiActionRequest.from_action(
                coordinator1.execute_action.await_args.args[0]
            ).payload
            == 'Configured(-1, "office")'
        )
        await hass.services.async_call(
            "grenton",
            "run_scene",
            {"parameter": ""},
            target={"device_id": scene1.registry_entry.device_id},
            blocking=True,
        )
        assert (
            GrentonCluApiActionRequest.from_action(
                coordinator1.execute_action.await_args.args[0]
            ).payload
            == "Configured()"
        )
        assert scene1._config == saved
        await hass.services.async_call(
            "grenton",
            "run_scene",
            {"parameter": "7"},
            target={"entity_id": [scene1.entity_id, scene2.entity_id]},
            blocking=True,
        )
        assert (
            GrentonCluApiActionRequest.from_action(
                coordinator1.execute_action.await_args.args[0]
            ).payload
            == "Configured(7)"
        )
        assert (
            GrentonCluApiActionRequest.from_action(
                coordinator2.execute_action.await_args.args[0]
            ).payload
            == "Evening(7)"
        )
        # Ordinary Grenton buttons are unaffected by run_scene.
        ordinary = ButtonEntity()
        ordinary.entity_id = "button.ordinary"
        ordinary.async_press = AsyncMock()
        await platform1.async_add_entities([ordinary])
        coordinator1.execute_action.reset_mock()
        await hass.services.async_call(
            "grenton",
            "run_scene",
            {"parameter": "7"},
            target={"entity_id": [scene1.entity_id, ordinary.entity_id]},
            blocking=True,
        )
        ordinary.async_press.assert_not_awaited()
        coordinator1.execute_action.assert_awaited_once()
        await platform2.async_reset()
        coordinator2.execute_action.reset_mock()
        await hass.services.async_call(
            "grenton",
            "run_scene",
            {},
            target={"entity_id": scene2.entity_id},
            blocking=True,
        )
        coordinator2.execute_action.assert_not_awaited()
        await platform1.async_reset()

    asyncio.run(run())


@pytest.mark.parametrize("language", ["en", "pl"])
def test_upstream_scene_action_metadata_and_translations(language):
    component = Path(__file__).parents[1] / "custom_components/homeassistant_grenton"
    metadata = yaml.safe_load((component / "services.yaml").read_text())["run_scene"]
    selector.TargetSelector(metadata["target"])
    assert metadata["target"]["entity"]["domain"] == "button"
    assert set(metadata["fields"]) == {"parameter"}
    assert metadata["fields"]["parameter"]["required"] is False
    assert (
        selector.selector(metadata["fields"]["parameter"]["selector"])(
            metadata["fields"]["parameter"]["example"]
        )
        == '"123"'
    )
    translations = json.loads((component / f"translations/{language}.json").read_text())
    assert translations["services"]["run_scene"]["name"]
    assert set(translations["services"]["run_scene"]["fields"]) == {"parameter"}
