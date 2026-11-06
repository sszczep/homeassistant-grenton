"""CLU diagnostics use slow reads without driving whole-group realtime reports."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from test_clu_scripts import make_entry, make_hass
from test_clu_state import coordinator, make_clu
from test_clu_variables import set_options

from custom_components.homeassistant_grenton.domain.entities.clu_state import (
    GrentonCluBusVoltage,
    GrentonCluCloudConnection,
    GrentonCluFirmwareVersion,
    GrentonCluUptime,
    GrentonCluUseCloud,
)
from custom_components.homeassistant_grenton.domain.state_object import (
    GrentonAttributeValueObject,
)
from custom_components.homeassistant_grenton.state import MISSING_STATE

CLU_VALUES = [
    pytest.param(GrentonCluUptime, "0", "native_value", 3600, 0, id="uptime"),
    pytest.param(
        GrentonCluBusVoltage, "27", "native_value", 24.5, 0, id="bus_voltage"
    ),
    pytest.param(
        GrentonCluCloudConnection, "19", "is_on", True, False, id="cloud_connection"
    ),
    pytest.param(GrentonCluUseCloud, "18", "is_on", True, False, id="use_cloud"),
    pytest.param(
        GrentonCluFirmwareVersion,
        "17",
        "native_value",
        "1.20",
        "00123",
        id="firmware_version",
    ),
]


@pytest.mark.parametrize(
    "entity_class,index,value_property,initial,updated", CLU_VALUES
)
def test_builtin_value_uses_each_clus_slow_interval_and_preserves_value_types(
    tmp_path, entity_class, index, value_property, initial, updated
):
    async def run():
        entry = make_entry()
        set_options(entry, {"clu_read_settings": {"clu2": {"slow_read_interval": 10}}})
        hass = await make_hass(tmp_path, [entry])
        clus = [make_clu("clu1"), make_clu("clu2")]
        coord = coordinator(hass, entry, clus)
        entities = [entity_class(coord, clu) for clu in clus]
        for entity in entities:
            clu_id = entity.clu.id
            api = coord._apis[clu_id]
            key = coord._state_key(entity.state_object)
            assert key.name == index
            assert key not in coord._realtime_keys[clu_id]
            assert key in coord._slow_keys[clu_id]
            assert coord.state_read_mode(entity.state_object) == "slow"
            api.register_component_states = AsyncMock()
            api.poll_component_states = AsyncMock(return_value=[initial])
            assert await coord.async_refresh_clu_state(clu_id)
            api.register_component_states.assert_not_awaited()
            api.poll_component_states.assert_awaited_once_with([key])
            assert getattr(entity, value_property) == initial
            api.poll_component_states.return_value = [updated]
            await coord._send_slow_poll(clu_id)
            assert getattr(entity, value_property) == updated
        assert coord._slow_read_intervals == {"clu1": 60, "clu2": 10}
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("realtime_first", [False, True])
@pytest.mark.parametrize(
    "entity_class,index,value_property,initial,updated", CLU_VALUES
)
def test_explicit_realtime_consumer_of_builtin_value_keeps_existing_precedence(
    tmp_path, realtime_first, entity_class, index, value_property, initial, updated
):
    async def run():
        entry = make_entry()
        hass = await make_hass(tmp_path, [entry])
        clu = make_clu("clu1")
        coord = coordinator(hass, entry, [clu])
        shared = GrentonAttributeValueObject(clu.id, clu.id, index)
        if realtime_first:
            coord.register_component_state(shared)
        entity = entity_class(coord, clu)
        if not realtime_first:
            coord.register_component_state(shared)
        api = coord._apis[clu.id]
        api.register_component_states = AsyncMock(return_value=[initial])
        api.poll_component_states = AsyncMock()
        assert await coord.async_refresh_clu_state(clu.id)
        assert coord.state_read_mode(entity.state_object) == "realtime"
        api.register_component_states.assert_awaited_once_with(
            [coord._state_key(shared)]
        )
        api.poll_component_states.assert_not_awaited()
        assert getattr(entity, value_property) == initial
        await coord._process_report(clu.id, [coord._state_key(shared)], [updated])
        assert getattr(entity, value_property) == updated
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize(
    "entity_class,index,value_property,initial,updated", CLU_VALUES
)
def test_failed_builtin_value_poll_retains_cache_but_expires_visible_value(
    tmp_path, entity_class, index, value_property, initial, updated
):
    async def run():
        clock = [0]
        with patch(
            "custom_components.homeassistant_grenton.coordinator.monotonic",
            side_effect=lambda: clock[0],
        ):
            entry = make_entry()
            hass = await make_hass(tmp_path, [entry])
            clu = make_clu("clu1")
            coord = coordinator(hass, entry, [clu])
            entity = entity_class(coord, clu)
            assert entity.state_object.index == index
            api = coord._apis[clu.id]
            api.poll_component_states = AsyncMock(return_value=[initial])
            await coord._send_slow_poll(clu.id)
            api.poll_component_states.return_value = [MISSING_STATE]
            clock[0] = 60
            await coord._send_slow_poll(clu.id)
            assert getattr(entity, value_property) == initial
            clock[0] = 120
            await coord._send_slow_poll(clu.id)
            assert getattr(entity, value_property) is None
            assert coord.state.get_value_for_component(entity.state_object) == initial
            api.poll_component_states.return_value = [updated]
            clock[0] = 121
            await coord._send_slow_poll(clu.id)
            assert getattr(entity, value_property) == updated
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())
