"""CLU attribute subscriptions, native HA entities and cloud control."""

import asyncio
import json
import logging
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
from test_clu_scripts import make_clu as make_controller_clu
from test_clu_scripts import make_entry, make_hass

from custom_components.homeassistant_grenton import _cleanup_orphans, async_setup
from custom_components.homeassistant_grenton.binary_sensor import (
    async_setup_entry as setup_binary_sensors,
)
from custom_components.homeassistant_grenton.coordinator import GrentonCoordinator
from custom_components.homeassistant_grenton.domain.api.clu import (
    GrentonCluApiProtocol,
)
from custom_components.homeassistant_grenton.domain.api.clu_messages import (
    GrentonCluApiFetchValuesRequest,
)
from custom_components.homeassistant_grenton.domain.api.clu_messages.action import (
    GrentonCluApiActionRequest,
)
from custom_components.homeassistant_grenton.domain.api.clu_messages.client_register import (
    GrentonCluApiClientRegisterRequest,
    GrentonCluApiClientRegisterResponse,
)
from custom_components.homeassistant_grenton.domain.clu import GrentonClu
from custom_components.homeassistant_grenton.domain.device_types import (
    CLU_GATE_HTTP,
    CLU_SERIAL_PREFIXES,
    CLU_Z_WAVE,
    DEVICE_ATTRIBUTES,
)
from custom_components.homeassistant_grenton.domain.encryption import GrentonEncryption
from custom_components.homeassistant_grenton.domain.entities.clu_state import (
    GrentonCluBusVoltage,
    GrentonCluCloudConnection,
    GrentonCluFirmwareVersion,
    GrentonCluStateEntity,
    GrentonCluUptime,
    GrentonCluUseCloud,
    clu_entities,
)
from custom_components.homeassistant_grenton.dto.clu import GrentonCluDto
from custom_components.homeassistant_grenton.integration_config import RuntimeData
from custom_components.homeassistant_grenton.sensor import (
    async_setup_entry as setup_sensors,
)
from custom_components.homeassistant_grenton.state import (
    GrentonCluStateAttributeKey,
    GrentonCluStateVariableKey,
)
from custom_components.homeassistant_grenton.switch import (
    async_setup_entry as setup_switches,
)


def make_clu(clu_id, name="Main CLU", prefix="221"):
    clu = make_controller_clu(clu_id, name)
    clu.serial_number = prefix + ("000921" if clu_id == "clu1" else "000922")
    return clu


def coordinator(hass, entry, clus):
    return GrentonCoordinator(
        hass,
        entry,
        clus,
        GrentonEncryption("AAAAAAAAAAAAAAAAAAAAAA==", "AAAAAAAAAAAAAAAAAAAAAA=="),
    )


async def register_platforms(hass, entry):
    translations = json.loads(
        (
            Path(__file__).parents[1]
            / "custom_components/homeassistant_grenton/translations/en.json"
        ).read_text()
    )["entity"]
    platforms = []
    for domain, setup in [
        ("sensor", setup_sensors),
        ("binary_sensor", setup_binary_sensors),
        ("switch", setup_switches),
    ]:
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
        names = {
            f"component.grenton.entity.{domain}.{key}.name": value["name"]
            for key, value in translations[domain].items()
            if "name" in value
        }
        platform.platform_data.platform_translations = names
        platform.platform_data.object_id_platform_translations = names
        platform.platform_data.default_language_platform_translations = names
        collected = Mock()
        await setup(hass, entry, collected)
        await platform.async_add_entities(collected.call_args.args[0])
        platforms.append(platform)
    return platforms


def test_supported_attributes_poll_on_each_clu_and_update_native_entities(tmp_path):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        clus = [make_clu("clu1"), make_clu("clu2", "Second CLU", "521")]
        coord = coordinator(hass, entry, clus)
        entities = [entity for clu in clus for entity in clu_entities(coord, clu)]
        entry.runtime_data = RuntimeData(coord, [], entities)
        for clu in clus:
            keys = coord.state.clus[clu.id].get_subscription_order()
            indexes = ["0", "19", "18", "17"]
            values = [123, True, False, "3.1.0"]
            if clu.device_type == CLU_Z_WAVE:
                indexes.append("27")
                values.append(24.5)
            assert [key.name for key in keys] == indexes
            assert all(isinstance(key, GrentonCluStateAttributeKey) for key in keys)
            assert all(key.object_name == clu.id for key in keys)
            expected = ",".join(f"{{{clu.id},{index}}}" for index in indexes)
            assert GrentonCluApiClientRegisterRequest(keys, 0).payload == (
                f"SYSTEM:clientRegister(0,0,1,{{{expected}}})"
            )
            values_by_key = dict(zip(keys, values))
            api = coord._apis[clu.id]
            api.register_component_states = AsyncMock(
                side_effect=lambda requested, values=values_by_key: [
                    values[key] for key in requested
                ]
            )
            api.poll_component_states = AsyncMock(
                side_effect=lambda requested, values=values_by_key: [
                    values[key] for key in requested
                ]
            )
            assert await coord.async_refresh_clu_state(clu.id)
            api.register_component_states.assert_not_awaited()
            api.poll_component_states.assert_awaited_once_with(keys)
        platforms = await register_platforms(hass, entry)
        assert [len(platform.entities) for platform in platforms] == [11, 4, 2]
        registry = er.async_get(hass)
        device_registry = dr.async_get(hass)
        assert len(device_registry.devices) == 2
        for clu in clus:
            group = [entity for entity in entities if entity.clu.id == clu.id]
            device_ids = {
                registry.async_get(entity.entity_id).device_id for entity in group
            }
            assert len(device_ids) == 1
            controller, uptime, cloud, use_cloud, firmware = group[:5]
            device = device_registry.async_get(next(iter(device_ids)))
            assert device.sw_version == "3.1.0"
            assert device.model == clu.device_type
            if clu.device_type == CLU_Z_WAVE:
                voltage = group[5]
                assert hass.states.get(voltage.entity_id).state == "24.5"
                assert voltage.device_class == SensorDeviceClass.VOLTAGE
                assert voltage.native_unit_of_measurement == "V"
                assert voltage.state_class.value == "measurement"
            else:
                assert len(group) == 8
            assert hass.states.get(controller.entity_id).state == clu.serial_number
            assert hass.states.get(uptime.entity_id).state == "123"
            assert uptime.device_class == SensorDeviceClass.DURATION
            assert uptime.native_unit_of_measurement == "s"
            assert hass.states.get(cloud.entity_id).state == "on"
            assert cloud.device_class == BinarySensorDeviceClass.CONNECTIVITY
            assert hass.states.get(use_cloud.entity_id).state == "off"
            assert use_cloud.entity_category == EntityCategory.CONFIG
            assert all(
                entity.entity_category == EntityCategory.DIAGNOSTIC
                for entity in [uptime, cloud, firmware]
            )
            assert hass.states.get(firmware.entity_id).state == "3.1.0"

        # A poll changes only its own CLU, including a reboot and new firmware.
        coord._apis["clu1"].poll_component_states = AsyncMock(
            return_value=[0, False, True, "3.2.0", 24.5]
        )
        await coord._send_slow_poll("clu1")
        assert entities[1].native_value == 0
        assert entities[2].is_on is False
        assert entities[3].is_on is True
        second_uptime = next(
            entity for entity in entities if entity.unique_id == "clu_clu2_uptime"
        )
        assert second_uptime.native_value == 123
        first_device_id = entities[0].registry_entry.device_id
        assert device_registry.async_get(first_device_id).sw_version == "3.2.0"

        # The run_script device target still runs once for its own CLU.
        await async_setup(hass, {})
        coord.execute_action = AsyncMock()
        await hass.services.async_call(
            "grenton",
            "run_script",
            {"script": "Actions"},
            target={"device_id": first_device_id},
            blocking=True,
        )
        coord.execute_action.assert_awaited_once()
        assert coord.execute_action.await_args.args[0].clu_id == "clu1"

        # Reload/reconfigure preserves all surviving identities and removes
        # diagnostics and configuration entities belonging to a removed CLU.
        kept = {entity.entity_id for entity in entities if entity.clu.id == "clu1"}
        removed = {entity.entity_id for entity in entities if entity.clu.id == "clu2"}
        removed_device_id = second_uptime.registry_entry.device_id
        for platform in platforms:
            await platform.async_reset()
        replacement = clu_entities(coord, clus[0])
        _cleanup_orphans(hass, entry, [], replacement)
        assert all(registry.async_get(entity_id) for entity_id in kept)
        assert all(registry.async_get(entity_id) is None for entity_id in removed)
        assert device_registry.async_get(removed_device_id) is None
        assert device_registry.async_get(first_device_id).sw_version == "3.2.0"
        entry.runtime_data.clu_entities = replacement
        reloaded = await register_platforms(hass, entry)
        assert {entity.entity_id for entity in replacement} == kept
        for platform in reloaded:
            await platform.async_reset()

    asyncio.run(run())


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        ("false", False),
        ("1", True),
        ("0", False),
        (None, None),
        ("", None),
        ("invalid", None),
    ],
)
def test_boolean_attributes_preserve_false_and_unknown_values(
    tmp_path, value, expected
):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu1")
        coord = coordinator(hass, entry, [clu])
        for cls in [GrentonCluCloudConnection, GrentonCluUseCloud]:
            entity = cls(coord, clu)
            assert entity.is_on is None
            keys = coord.state.clus[clu.id].get_subscription_order()
            coord._apis[clu.id].poll_component_states = AsyncMock(
                return_value=[value] * len(keys)
            )
            await coord._send_slow_poll(clu.id)
            assert entity.is_on is expected

    asyncio.run(run())


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, 0),
        (123, 123),
        ("123", 123),
        (123.0, 123),
        (1.5, None),
        (-1, None),
        (True, None),
        (None, None),
        ("", None),
        ("invalid", None),
    ],
)
def test_uptime_is_a_nonnegative_integer_or_unknown(tmp_path, value, expected):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu1")
        coord = coordinator(hass, entry, [clu])
        entity = GrentonCluUptime(coord, clu)
        coord._apis[clu.id].poll_component_states = AsyncMock(return_value=[value])
        await coord._send_slow_poll(clu.id)
        assert entity.native_value == expected

    asyncio.run(run())


@pytest.mark.parametrize("prefix", ["221", "521"])
def test_use_cloud_writes_boolean_to_correct_clu_and_reads_back_without_assuming_success(
    tmp_path,
    prefix,
):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu2", prefix=prefix)
        coord = coordinator(hass, entry, [clu])
        entity = GrentonCluUseCloud(coord, clu)
        keys = coord.state.clus[clu.id].get_subscription_order()
        coord.state.clus[clu.id].update_keys(keys, [False])
        api = SimpleNamespace(
            execute_action=AsyncMock(return_value=True),
            register_component_states=AsyncMock(return_value=[False]),
            state_read_batches=coord._apis[clu.id].state_read_batches,
        )
        api.poll_component_states = AsyncMock(return_value=[False])
        read = api.poll_component_states
        coord._apis[clu.id] = api
        await entity.async_turn_on()
        action = api.execute_action.await_args.args[0]
        assert action.clu_id == "clu2"
        assert (
            GrentonCluApiActionRequest.from_action(action).payload
            == f"{clu.id}:set(18,true)"
        )
        read.assert_awaited_once_with(keys)
        assert entity.is_on is False, (
            "a successful request must not invent a changed CLU setting"
        )
        read.return_value = [True]
        await entity.async_turn_on()
        assert entity.is_on is True
        read.return_value = [False]
        await entity.async_turn_off()
        assert (
            GrentonCluApiActionRequest.from_action(
                api.execute_action.await_args.args[0]
            ).payload
            == f"{clu.id}:set(18,false)"
        )
        assert entity.is_on is False
        api.execute_action.return_value = False
        read.reset_mock()
        with pytest.raises(HomeAssistantError, match="rejected"):
            await entity.async_turn_on()
        read.assert_not_awaited()
        api.register_component_states.assert_not_awaited()
        assert entity.is_on is False

    asyncio.run(run())


@pytest.mark.parametrize("prefix", ["221", "521"])
def test_firmware_strings_survive_polled_responses_and_notification_parsing(
    tmp_path, prefix
):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu1", prefix=prefix)
        coord = coordinator(hass, entry, [clu])
        firmware = GrentonCluFirmwareVersion(coord, clu)
        keys = coord.state.clus[clu.id].get_subscription_order()
        api = coord._apis[clu.id]
        response = 'resp:192.0.2.1:abcd:values:{"1.20"}'
        api.protocol = SimpleNamespace(send_request=AsyncMock(return_value=response))
        await coord._send_slow_poll(clu.id)
        api.protocol.send_request.assert_awaited_once()
        assert isinstance(
            api.protocol.send_request.await_args.args[0],
            GrentonCluApiFetchValuesRequest,
        )
        assert firmware.native_value == "1.20"
        assert firmware.device_info["sw_version"] == "1.20"
        protocol = GrentonCluApiProtocol(api)
        protocol.subscription_keys = keys

        async def handle_report(values):
            await coord._process_report(clu.id, keys, values)

        protocol.subscription_callback = AsyncMock(side_effect=handle_report)
        protocol._process_response('resp:192.0.2.1:00000000:clientReport:0:{"00123"}')
        await asyncio.sleep(0)
        assert firmware.native_value == "00123"
        # Unrelated numeric/boolean variables keep their existing decoding.
        assert GrentonCluApiClientRegisterResponse(
            "resp:192.0.2.1:abcd:clientReport:0:{123,false}"
        ).values == [123, False]

    asyncio.run(run())


# Synthetic serials retain only the prefixes needed for device-type detection.
@pytest.mark.parametrize(
    "serial,expected",
    [("221000001", CLU_Z_WAVE), ("521000002", CLU_GATE_HTTP), ("999123", None)],
)
def test_serial_detection_and_unknown_type_preserves_controller(
    tmp_path, serial, expected
):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        clu = make_controller_clu("clu1", "Renamed controller")
        clu.serial_number = serial
        coord = coordinator(hass, entry, [clu])
        entities = clu_entities(coord, clu)
        assert clu.device_type == expected
        assert clu.object_name == clu.id
        assert entities[0].unique_id == "clu_clu1"
        assert entities[0].device_info["model"] == (expected or "CLU")
        if expected is None:
            assert len(entities) == 4
            assert not coord.state.clus[clu.id].get_subscription_order()
        else:
            assert {
                int(entity.state_object.index)
                for entity in entities
                if isinstance(entity, GrentonCluStateEntity)
            } == set(DEVICE_ATTRIBUTES[expected])
            assert entities[1].unique_id == "clu_clu1_uptime"

    asyncio.run(run())


@pytest.mark.parametrize(
    "value,expected",
    [
        (24, 24.0),
        (24.75, 24.75),
        ("23.5", 23.5),
        (0, 0.0),
        (None, None),
        (True, None),
        ("invalid", None),
        (float("inf"), None),
        (float("nan"), None),
    ],
)
def test_bus_voltage_is_a_finite_measurement(tmp_path, value, expected):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu1")
        coord = coordinator(hass, entry, [clu])
        voltage = GrentonCluBusVoltage(coord, clu)
        coord._apis[clu.id].poll_component_states = AsyncMock(return_value=[value])
        await coord._send_slow_poll(clu.id)
        assert voltage.native_value == expected
        assert voltage.entity_category == EntityCategory.DIAGNOSTIC

    asyncio.run(run())


def test_firmware_decoding_does_not_change_other_objects_or_variables():
    clu = make_clu("clu1")
    keys = [
        GrentonCluStateAttributeKey("DOUT1", "17"),
        GrentonCluStateVariableKey("FirmwareVersion"),
        GrentonCluStateAttributeKey("CLU221000001", "17"),
    ]
    assert GrentonCluApiClientRegisterResponse(
        'resp:192.0.2.1:abcd:clientReport:0:{"1.20","00123","1.20"}', keys, clu
    ).values == [1.2, 123, 1.2]


def test_new_type_uses_its_own_indexes_and_skips_unsupported_entities(
    tmp_path, monkeypatch
):
    monkeypatch.setitem(CLU_SERIAL_PREFIXES, "621", "FUTURE_CLU")
    monkeypatch.setitem(
        DEVICE_ATTRIBUTES, "FUTURE_CLU", {42: "FirmwareVersion", 31: "BusVoltage"}
    )

    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu1", prefix="621")
        coord = coordinator(hass, entry, [clu])
        entities = clu_entities(coord, clu)
        assert len(entities) == 6
        assert isinstance(entities[1], GrentonCluFirmwareVersion)
        assert isinstance(entities[2], GrentonCluBusVoltage)
        keys = coord.state.clus[clu.id].get_subscription_order()
        assert [key.name for key in keys] == ["42", "31"]
        values = GrentonCluApiClientRegisterResponse(
            'resp:192.0.2.1:abcd:clientReport:0:{"1.20",24.5}', keys, clu
        ).values
        coord._apis[clu.id].poll_component_states = AsyncMock(return_value=values)
        await coord._send_slow_poll(clu.id)
        assert entities[1].native_value == "1.20"
        assert entities[2].native_value == 24.5

    asyncio.run(run())


@pytest.mark.parametrize(
    "object_id,serial,device_type,indexes",
    [
        ("CLU900001", "221000001", CLU_Z_WAVE, ["0", "19", "18", "17", "27"]),
        ("CLU521000002", "521000002", CLU_GATE_HTTP, ["0", "19", "18", "17"]),
    ],
)
def test_imported_clu_id_addresses_attributes_independently_of_serial(
    tmp_path, object_id, serial, device_type, indexes
):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        clu = GrentonClu.from_dto(
            GrentonCluDto(
                id=object_id,
                serialNumber=serial,
                name="Renamed CLU",
                ip="192.0.2.1",
                port=1234,
                connectionType="LOCAL_ONLY",
            )
        )
        coord = coordinator(hass, entry, [clu])
        entities = clu_entities(coord, clu)
        assert clu.device_type == device_type
        assert clu.object_name == object_id
        keys = coord.state.clus[clu.id].get_subscription_order()
        assert keys == [
            GrentonCluStateAttributeKey(object_id, index) for index in indexes
        ]
        expected = ",".join(f"{{{object_id},{index}}}" for index in indexes)
        assert GrentonCluApiClientRegisterRequest(keys, 0).payload == (
            f"SYSTEM:clientRegister(0,0,1,{{{expected}}})"
        )
        report = '123,true,false,"1.20"'
        if device_type == CLU_Z_WAVE:
            report += ",24.5"
        values = GrentonCluApiClientRegisterResponse(
            f"resp:192.0.2.1:abcd:clientReport:0:{{{report}}}", keys, clu
        ).values
        coord._apis[clu.id].poll_component_states = AsyncMock(return_value=values)
        await coord._send_slow_poll(clu.id)
        firmware = next(
            entity
            for entity in entities
            if isinstance(entity, GrentonCluFirmwareVersion)
        )
        assert firmware.native_value == "1.20"
        coord.execute_action = AsyncMock()
        coord.async_refresh_clu_state = AsyncMock()
        use_cloud = next(
            entity for entity in entities if isinstance(entity, GrentonCluUseCloud)
        )
        await use_cloud.async_turn_on()
        action = coord.execute_action.await_args.args[0]
        assert action.clu_id == object_id
        assert (
            GrentonCluApiActionRequest.from_action(action).payload
            == f"{object_id}:set(18,true)"
        )
        coord.async_refresh_clu_state.assert_awaited_once_with(object_id)

    asyncio.run(run())
