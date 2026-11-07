"""Restoring lights after a CLU restart (uptime reset)."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service

from homeassistant.core import HomeAssistant

from custom_components.grenton.restore import LightRestoreManager

CLU = "CLU221000001"


def _light(entity_id):
    return SimpleNamespace(
        entity_id=entity_id, unique_id=f"uid_{entity_id}",
        state_sources=[SimpleNamespace(clu_id=CLU)],
    )


async def _manager(hass, exclude=(), entry=None):
    if entry is None:
        entry = MockConfigEntry(domain="grenton", data={})
        entry.add_to_hass(hass)
    coordinator = SimpleNamespace(_send_slow_poll=AsyncMock())
    lights = [_light("light.salon"), _light("light.kuchnia"), _light("light.taras")]
    uptime = SimpleNamespace(entity_id="sensor.clu_uptime")
    manager = LightRestoreManager(hass, entry, coordinator, lights, {CLU: uptime}, set(exclude))
    return manager, coordinator


async def test_restore_after_clu_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    on = async_mock_service(hass, "light", "turn_on")
    off = async_mock_service(hass, "light", "turn_off")
    hass.states.async_set("sensor.clu_uptime", "86400")
    hass.states.async_set("light.salon", "on", {"brightness": 128, "hs_color": [30.0, 80.0]})
    hass.states.async_set("light.kuchnia", "off")
    hass.states.async_set("light.taras", "on", {"brightness": 255})

    manager, coordinator = await _manager(hass, exclude={"light.taras"})
    await manager.async_start()

    # Power failure: lights go unavailable, the CLU comes back with all lights off
    freezer.tick(timedelta(minutes=10))
    for entity_id in ("light.salon", "light.kuchnia", "light.taras"):
        hass.states.async_set(entity_id, "unavailable")
    freezer.tick(timedelta(seconds=60))
    for entity_id in ("light.salon", "light.kuchnia", "light.taras"):
        hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    coordinator._send_slow_poll.assert_awaited_with(CLU)  # uptime read at once after reconnect

    hass.states.async_set("sensor.clu_uptime", "40")
    await hass.async_block_till_done()

    assert [c.data["entity_id"] for c in on] == ["light.salon"]
    assert on[0].data["brightness"] == 128 and on[0].data["hs_color"] == [30.0, 80.0]
    assert off == []  # kuchnia already off, taras excluded
    await manager.async_stop()


async def test_no_restore_without_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set("sensor.clu_uptime", "1000")
    hass.states.async_set("light.salon", "on", {"brightness": 200})
    manager, _ = await _manager(hass)
    await manager.async_start()

    freezer.tick(timedelta(minutes=5))
    hass.states.async_set("light.salon", "unavailable")
    hass.states.async_set("light.salon", "off")       # user turned it off while offline? no restart
    hass.states.async_set("sensor.clu_uptime", "1300")  # uptime kept counting
    await hass.async_block_till_done()
    assert on == []
    await manager.async_stop()


async def test_restart_while_ha_was_down(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    """History survives in the Store; restart detected on the next start."""
    on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set("sensor.clu_uptime", "5000")
    hass.states.async_set("light.salon", "on", {"brightness": 90})
    manager, _ = await _manager(hass)
    await manager.async_start()
    await manager.async_stop()
    entry = manager.entry

    freezer.tick(timedelta(hours=1))
    hass.states.async_set("light.salon", "off")
    hass.states.async_set("sensor.clu_uptime", "120")
    manager, _ = await _manager(hass, entry=entry)
    await manager.async_start()
    await hass.async_block_till_done()
    assert [c.data for c in on] == [{"entity_id": "light.salon", "brightness": 90}]
    await manager.async_stop()


async def test_options_step_and_setup(hass: HomeAssistant):
    from unittest.mock import patch
    from homeassistant.data_entry_flow import FlowResultType
    from test_hybrid import INTERFACE

    options = {"manual_objects": [{"id": "l1", "kind": "light", "name": "Lampa", "transport": "udp",
                                   "grenton_id": "CLU221000001->DOU0005", "area": ""}]}
    entry = MockConfigEntry(domain="grenton", unique_id="iface1", title="iface1", options=options,
                            data={"ip_address": "x", "port": "9998", "pin": "1", "interface": INTERFACE})
    entry.add_to_hass(hass)
    api = "custom_components.grenton.domain.api.clu.GrentonCluApi"

    async def register(self, keys):
        return [0 for _ in keys]
    with patch(f"{api}.connect", AsyncMock(return_value=True)), \
         patch(f"{api}.ping", AsyncMock(return_value=True)), \
         patch(f"{api}.register_component_states", register), \
         patch(f"{api}.disconnect", AsyncMock()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.restore_manager is None

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert "restore_lights" in result["menu_options"]
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "restore_lights"})
        assert result["type"] == FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"enabled": True, "exclude": []})
        assert result["type"] == FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

        assert entry.options["restore_lights"] == {"enabled": True, "exclude": []}
        manager = entry.runtime_data.restore_manager
        assert manager is not None
        assert list(manager._light_clu.values()) == ["CLU221000001"]
        assert await hass.config_entries.async_unload(entry.entry_id)
