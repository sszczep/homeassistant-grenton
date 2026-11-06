"""Health from existing traffic, source-level availability and native diagnostics."""

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
from test_clu_lifecycle import fixture
from test_clu_protocol_lifecycle import Socket, tick
from test_clu_scripts import make_entry, make_hass
from test_clu_state import coordinator, make_clu, register_platforms
from test_on_off_configuration import widget

from custom_components.homeassistant_grenton import _cleanup_orphans
from custom_components.homeassistant_grenton.domain.api.clu import (
    GrentonCluApiProtocol,
    _SubscriptionGroup,
)
from custom_components.homeassistant_grenton.domain.api.clu_messages import (
    GrentonCluApiPingRequest,
)
from custom_components.homeassistant_grenton.domain.entities.clu_diagnostics import (
    connection_diagnostics,
)
from custom_components.homeassistant_grenton.integration_config import RuntimeData
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper
from custom_components.homeassistant_grenton.state import GrentonCluStateVariableKey


async def report(coord, clu_id, keys, values):
    # The fake feed stands in for the protocol that records incoming packets.
    coord.connection_health[clu_id].record_response()
    await coord._process_report(clu_id, keys, values)


def successful_ping(coord, clu_id):
    coord.connection_health[clu_id].record_response()
    return True


def clock_patches(clock):
    return (
        patch(
            "custom_components.homeassistant_grenton.domain.api.clu_health.monotonic",
            side_effect=lambda: clock[0],
        ),
        patch(
            "custom_components.homeassistant_grenton.coordinator.monotonic",
            side_effect=lambda: clock[0],
        ),
    )


def test_outage_changes_only_affected_clu_entities_and_recovers_without_recreating_them(
    tmp_path,
):
    async def run():
        clock = [0]
        health_clock, state_clock = clock_patches(clock)
        with health_clock, state_clock:
            entry = make_entry()
            hass = await make_hass(tmp_path, [entry])
            clus = [make_clu("clu1"), make_clu("clu2")]
            coord = coordinator(hass, entry, clus)
            devices = []
            for index, clu in enumerate(clus):
                dto = widget()
                dto.id = f"switch{index}"
                dto.components[0].state.cluId = clu.id
                devices.append(DeviceMapper.to_domain(dto, coord))
                coord._apis[clu.id].ping = AsyncMock(return_value=False)
                await report(
                    coord,
                    clu.id,
                    [coord._state_key(devices[-1].entities[0].state_object)],
                    [1],
                )
            entities = [device.entities[0] for device in devices]
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
            try:
                await platform.async_add_entities(entities)
                assert all(
                    hass.states.get(entity.entity_id).state == "on"
                    for entity in entities
                )
                clock[0] = 29
                await coord._send_ping("clu1")
                assert entities[0].available
                clock[0] = 30
                await report(
                    coord, "clu2", [coord._state_key(entities[1].state_object)], [1]
                )
                await coord._send_ping("clu1")
                assert hass.states.get(entities[0].entity_id).state == "unavailable"
                assert hass.states.get(entities[1].entity_id).state == "on"
                clock[0] = 40
                coord._apis["clu1"].ping.side_effect = lambda: successful_ping(
                    coord, "clu1"
                )
                await coord._send_ping("clu1")
                assert hass.states.get(entities[0].entity_id).state == "on"
                assert entities[0].unique_id == "switch0_0"
            finally:
                await platform.async_reset()
                await coord.async_shutdown()
                await hass.async_stop()

    asyncio.run(run())


def test_keepalives_do_not_keep_stale_realtime_values_available_or_wake_all_entities(
    tmp_path,
):
    async def run():
        clock = [0]
        health_clock, state_clock = clock_patches(clock)
        with health_clock, state_clock:
            hass, _, coord, api = await fixture(tmp_path)
            dto = widget(double=True)
            first, second = DeviceMapper.to_domain(dto, coord).entities
            keys = [coord._state_key(entity.state_object) for entity in (first, second)]
            await report(coord, "clu1", keys, [1, 1])
            api.ping = AsyncMock(side_effect=lambda: successful_ping(coord, "clu1"))
            coord.async_set_updated_data = Mock()
            clock[0] = 5
            await coord._send_ping("clu1")
            assert first.available and second.available
            coord.async_set_updated_data.assert_not_called()
            clock[0] = 90
            await coord._send_ping("clu1")
            assert coord.connection_health["clu1"].connected is True
            assert not first.available and not second.available
            coord.async_set_updated_data.assert_called_once()
            await report(coord, "clu1", [keys[0]], [1])
            assert first.available and not second.available
            await coord.async_shutdown()
            await hass.async_stop()

    asyncio.run(run())


def test_diagnostics_add_no_reads_remain_available_offline_and_remove_their_listeners(
    tmp_path,
):
    async def run():
        clock = [0]
        health_clock, state_clock = clock_patches(clock)
        with health_clock, state_clock:
            hass, entry, coord, api = await fixture(tmp_path)
            clu = coord.clus[0]
            before = coord.state.clus[clu.id].get_subscription_order().copy()
            diagnostics = connection_diagnostics(coord, clu)
            assert coord.state.clus[clu.id].get_subscription_order() == before
            assert all(
                entity.translation_key != "clu_last_seen" for entity in diagnostics
            )
            registry = er.async_get(hass)
            obsolete = registry.async_get_or_create(
                "sensor", "grenton", f"clu_{clu.id}_last_seen", config_entry=entry
            )
            _cleanup_orphans(hass, entry, [], diagnostics)
            assert registry.async_get(obsolete.entity_id) is None
            entry.runtime_data = RuntimeData(coord, [], diagnostics)
            platforms = await register_platforms(hass, entry)
            connection, timeouts, subscriptions = diagnostics
            try:
                assert connection.is_on is None and api.health.last_seen is None
                assert timeouts.native_value == subscriptions.native_value == 0
                assert api.health is coord.connection_health[clu.id]
                api.ping = AsyncMock(side_effect=lambda: successful_ping(coord, "clu1"))
                await coord._send_ping(clu.id)
                await hass.async_block_till_done()
                seen = api.health.last_seen
                assert connection.is_on is True and seen.tzinfo is not None
                assert hass.states.get(connection.entity_id).state == "on"
                changes = []
                remove_listener = hass.bus.async_listen(
                    EVENT_STATE_CHANGED, changes.append
                )
                try:
                    clock[0] = 5
                    await coord._send_ping(clu.id)
                    await hass.async_block_till_done()
                    assert api.health.last_seen is not seen
                    assert not changes, "Keepalives must not create diagnostic activity"
                finally:
                    remove_listener()
                seen = api.health.last_seen
                clock[0] = 35
                api.ping.side_effect = None
                api.ping.return_value = False
                api.health.request_timeouts = 4
                await coord._send_ping(clu.id)
                await hass.async_block_till_done()
                assert hass.states.get(connection.entity_id).state == "off"
                assert api.health.last_seen == seen
                assert hass.states.get(timeouts.entity_id).state == "4"
                assert all(entity.available for entity in diagnostics)
                api.report_protocol = SimpleNamespace(active=True, closed=False)
                api._groups = [
                    _SubscriptionGroup(
                        [GrentonCluStateVariableKey("a")], 1, confirmed=True
                    ),
                    _SubscriptionGroup([GrentonCluStateVariableKey("b")], 2),
                    _SubscriptionGroup([GrentonCluStateVariableKey("c")], 3),
                ]
                assert subscriptions.native_value == 1
            finally:
                for platform in platforms:
                    await platform.async_reset()
                await coord.async_shutdown()
                await hass.async_stop()

    asyncio.run(run())


def test_timeouts_count_actual_requests_but_not_cancellation_or_unmatched_replies(
    tmp_path,
):
    async def run():
        hass, _, coord, api = await fixture(tmp_path)
        api.cipher = SimpleNamespace(encrypt=lambda data: data)
        protocol = GrentonCluApiProtocol(api)
        api.protocol = protocol
        socket = Socket(protocol, reply=False)
        protocol._response_timeout = 0
        assert await protocol.send_request(GrentonCluApiPingRequest("00000001")) is None
        assert api.health.request_timeouts == 1
        protocol._process_response("resp:192.0.2.1:deadbeef:pong")
        assert api.health.last_seen is None
        protocol._response_timeout = 5
        api._next_send_at = 0
        task = asyncio.create_task(
            protocol.send_request(GrentonCluApiPingRequest("00000002"))
        )
        await tick()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert api.health.request_timeouts == 1
        api._next_send_at = 0
        socket.reply = True
        await protocol.send_request(GrentonCluApiPingRequest("00000003"))
        assert api.health.last_seen is not None and api.health.connected
        await coord.async_shutdown()
        await hass.async_stop()

    asyncio.run(run())


@pytest.mark.parametrize("language", ["en", "pl"])
def test_connection_diagnostics_are_translated(language):
    import json
    from pathlib import Path

    data = json.loads(
        (
            Path(__file__).parents[1]
            / f"custom_components/homeassistant_grenton/translations/{language}.json"
        ).read_text()
    )["entity"]
    assert data["binary_sensor"]["clu_connection"]["name"]
    for key in ("clu_request_timeouts", "clu_subscriptions"):
        assert data["sensor"][key]["name"]
