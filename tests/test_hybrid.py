import base64
import json
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.grenton.domain.action import (
    GrentonActionAttribute, GrentonActionAttributeNumeric, GrentonActionMethodNumeric,
)
from custom_components.grenton.domain.api.clu_messages import GrentonCluApiActionRequest
from custom_components.grenton.domain.enums import GrentonActionEventType as E
from custom_components.grenton.gate import remote_lua
from custom_components.grenton.manual_objects import parse_grenton_id

GATE_URL = "http://10.0.0.50/HAlistener"
KEY = base64.b64encode(b"0123456789abcdef").decode()

INTERFACE = {
    "id": "iface1", "version": 1, "name": "Dom", "icon": "home", "theme": "GRENTON",
    "encryption": {"key": KEY, "iv": KEY},
    "clus": [{"id": "CLU221000001", "serialNumber": "221000001", "name": "CLU_Parter",
              "ip": "10.0.0.123", "port": 1234, "connectionType": "LOCAL_ONLY"}],
    "pages": [{"name": "Salon", "icon": "x", "isFullscreenWidget": False, "widgets": [{
        "id": "w1", "type": "ON_OFF", "components": [{
            "type": "BUTTON_BISTABLE", "label": "Lampa", "rowId": 0, "unit": "UNKNOWN",
            "onIndication": "ON", "offIndication": "OFF",
            "state": {"callType": "ATTRIBUTE", "cluId": "CLU221000001", "objectName": "DOU0001", "index": "0"},
            "actions": [
                {"callType": "METHOD", "event": "ON", "cluId": "CLU221000001", "objectName": "DOU0001", "index": "0", "value": "1"},
                {"callType": "METHOD", "event": "OFF", "cluId": "CLU221000001", "objectName": "DOU0001", "index": "0", "value": "0"},
            ]}]}]}],
    "pushNotifications": [],
}

OPTIONS = {
    "gate": {"url": GATE_URL, "scan_interval": 30},
    "manual_objects": [
        {"id": "aaa", "kind": "switch", "name": "Pompa", "grenton_id": "CLU221000001->DOU0002",
         "transport": "udp", "area": "Kotłownia"},
        {"id": "bbb", "kind": "climate", "name": "Termostat salon", "grenton_id": "CLU221000009->THE0001",
         "transport": "gate", "area": ""},
    ],
}


async def test_lua_building():
    assert parse_grenton_id(" CLU1 -> DOU2 ") == ("CLU1", "DOU2")
    quoted = GrentonCluApiActionRequest.from_action(GrentonActionAttribute("C", "DOU1", E.ON, "1", index="0")).payload
    numeric = GrentonCluApiActionRequest.from_action(GrentonActionAttributeNumeric("C", "DOU1", E.ON, "1", index="0")).payload
    text = GrentonCluApiActionRequest.from_action(GrentonActionMethodNumeric("C", "X", E.ON, 'a"b', index="2")).payload
    assert quoted == 'DOU1:set(0,"1")'
    assert numeric == "DOU1:set(0,1)"
    assert text == 'X:execute(2,"a\\"b")'
    assert remote_lua("CLU9", 'DOU1:set(0,"1")', returns=True) == 'return CLU9:execute(0, "DOU1:set(0,\\"1\\")")'


def _gate_values(lua):
    table = {"get(6)": 1, "get(7)": 0, "get(12)": 21.5, "get(14)": 20.5}
    for key, value in table.items():
        if key in lua:
            return value
    return None


async def test_hybrid_setup(hass: HomeAssistant, aioclient_mock):
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

    async def reply(method, url, data):
        body = data if isinstance(data, dict) else json.loads(data)
        out = {"g_status": "OK"}
        for k, lua in body.items():
            out[k] = 1 if k in ("status", "command") else _gate_values(lua)
        return AiohttpClientMockResponse(method, url, json=out)

    aioclient_mock.get(GATE_URL, side_effect=reply)
    entry = MockConfigEntry(domain="grenton", unique_id="iface1", title="iface1",
                            data={"ip_address": "x", "port": "9998", "pin": "1", "interface": INTERFACE},
                            options=OPTIONS)
    entry.add_to_hass(hass)
    api = "custom_components.grenton.domain.api.clu.GrentonCluApi"
    executed = []

    async def register(self, keys):
        return [1 for _ in keys]

    async def execute(self, action):
        executed.append(GrentonCluApiActionRequest.from_action(action).payload)
        return True

    with patch(f"{api}.connect", AsyncMock(return_value=True)), \
         patch(f"{api}.ping", AsyncMock(return_value=True)), \
         patch(f"{api}.register_component_states", register), \
         patch(f"{api}.execute_action", execute), \
         patch(f"{api}.disconnect", AsyncMock()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Interface widget, named from label, area from page
        lamp = hass.states.get("switch.lampa")
        assert lamp is not None and lamp.state == "on"
        # Manual UDP switch
        pump = hass.states.get("switch.pompa")
        assert pump is not None and pump.state == "on"
        # Manual Gate thermostat
        climate = hass.states.get("climate.termostat_salon")
        assert climate is not None
        assert climate.state == "heat"
        assert climate.attributes["temperature"] == 21.5
        assert climate.attributes["current_temperature"] == 20.5

        dev_reg = dr.async_get(hass)
        pump_dev = dev_reg.async_get_device(identifiers={("grenton", "manual_aaa")})
        assert pump_dev.name == "Pompa"
        lamp_dev = dev_reg.async_get_device(identifiers={("grenton", "w1")})
        assert lamp_dev.name == "Lampa"
        area_reg = __import__("homeassistant.helpers.area_registry", fromlist=["x"]).async_get(hass)
        assert area_reg.async_get_area(lamp_dev.area_id).name == "Salon"
        assert area_reg.async_get_area(pump_dev.area_id).name == "Kotłownia"

        # UDP manual action -> unquoted numeric Lua
        await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.pompa"}, blocking=True)
        assert executed[-1] == "DOU0002:set(0,0)"

        # Gate action -> wrapped in CLU:execute
        before = aioclient_mock.call_count
        await hass.services.async_call("climate", "set_temperature",
                                       {"entity_id": "climate.termostat_salon", "temperature": 22.5}, blocking=True)
        sent = [c[2] for c in aioclient_mock.mock_calls[before:]]
        commands = [b["command"] for b in sent if isinstance(b, dict) and "command" in b]
        assert commands == ['CLU221000009:execute(0, "THE0001:set(8,0)")',
                            'CLU221000009:execute(0, "THE0001:set(3,22.5)")'], sent

        await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow(hass: HomeAssistant, aioclient_mock):
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

    async def ok_reply(m, u, d):
        return AiohttpClientMockResponse(m, u, json={"g_status": "OK", "status": 1})
    aioclient_mock.get(GATE_URL, side_effect=ok_reply)
    entry = MockConfigEntry(domain="grenton", unique_id="iface1", title="iface1",
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

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == FlowResultType.MENU
        assert "remove_object" not in result["menu_options"]

        # Gate object without Gate configured -> error
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_object"})
        bad = {"kind": "switch", "name": "X", "grenton_id": "CLU221000009->DOU1", "transport": "gate"}
        result = await hass.config_entries.options.async_configure(result["flow_id"], bad)
        assert result["errors"] == {"transport": "gate_not_configured"}
        # UDP to a CLU outside the interface -> error
        result = await hass.config_entries.options.async_configure(result["flow_id"], {**bad, "transport": "udp"})
        assert result["errors"] == {"grenton_id": "clu_not_in_interface"}
        result = await hass.config_entries.options.async_configure(result["flow_id"], {**bad, "grenton_id": "nonsense"})
        assert result["errors"] == {"grenton_id": "invalid_grenton_id"}
        # Valid UDP object (match by CLU name)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**bad, "transport": "udp", "grenton_id": "CLU_Parter->DOU0005", "name": "Gniazdko"})
        assert result["type"] == FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert hass.states.get("switch.gniazdko") is not None  # reloaded with new object

        # Gate settings
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert "remove_object" in result["menu_options"]
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "gate_settings"})
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"url": "10.0.0.50/HAlistener", "scan_interval": 15})
        assert result["type"] == FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert entry.options["gate"] == {"url": GATE_URL, "scan_interval": 15}

        # Enabling push generates a webhook id and keeps it on later saves
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "gate_settings"})
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"url": GATE_URL, "scan_interval": 300, "push": True})
        await hass.async_block_till_done()
        hook = entry.options["gate"]["webhook_id"]
        assert hook
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "gate_settings"})
        assert hook in result["description_placeholders"]["webhook_url"]
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"url": GATE_URL, "scan_interval": 300, "push": True})
        await hass.async_block_till_done()
        assert entry.options["gate"]["webhook_id"] == hook
        assert len(entry.options["manual_objects"]) == 1

        # Remove
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "remove_object"})
        oid = entry.options["manual_objects"][0]["id"]
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"objects": [oid]})
        await hass.async_block_till_done()
        assert entry.options["manual_objects"] == []
        assert hass.states.get("switch.gniazdko") is None or hass.states.get("switch.gniazdko").state == "unavailable"
        await hass.config_entries.async_unload(entry.entry_id)


async def test_config_flow_custom_names(hass: HomeAssistant):
    api = "custom_components.grenton.domain.api.clu.GrentonCluApi"
    om = "custom_components.grenton.config_flow.GrentonObjectManagerApi"

    class FakeOM:
        def __init__(self, url): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def fetch_mobile_interface(self, pin): return INTERFACE

    async def register(self, keys):
        return [0 for _ in keys]

    with patch(om, FakeOM), \
         patch(f"{api}.connect", AsyncMock(return_value=True)), \
         patch(f"{api}.ping", AsyncMock(return_value=True)), \
         patch(f"{api}.register_component_states", register), \
         patch(f"{api}.disconnect", AsyncMock()):
        result = await hass.config_entries.flow.async_init("grenton", context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"ip_address": "1.2.3.4", "port": "9998", "pin": "1"})
        assert result["step_id"] == "naming"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"customize_names": True})
        assert result["step_id"] == "page_names"
        fields = [str(k) for k in result["data_schema"].schema]
        lamp_field = next(f for f in fields if f != "area")
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"area": "Pokój dzienny", lamp_field: "Żyrandol"})
        assert result["type"] == FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert hass.states.get("switch.zyrandol") is not None
        dev = dr.async_get(hass).async_get_device(identifiers={("grenton", "w1")})
        assert dev.name == "Żyrandol"


async def test_led_zwave_and_webhook(hass: HomeAssistant, aioclient_mock, hass_client_no_auth):
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

    values = {"LED0001:get(0)": 0.5, "LED0001:get(6)": "#ff8000", "LED0001:get(15)": 0,
              "ZWA0001:get(2)": 0, "ZWA0001:get(4)": 40, "ZWA0002:get(0)": 128, "LED0002:get(15)": 0}

    async def reply(method, url, data):
        out = {"g_status": "OK"}
        for k, lua in data.items():
            if k in ("status", "command"):
                out[k] = 1
                continue
            out[k] = next((v for key, v in values.items() if key in lua), None)
        return AiohttpClientMockResponse(method, url, json=out)

    aioclient_mock.get(GATE_URL, side_effect=reply)
    options = {
        "gate": {"url": GATE_URL, "scan_interval": 300, "webhook_id": "hook123"},
        "manual_objects": [
            {"id": "led", "kind": "led_rgbw", "name": "Taśma", "grenton_id": "CLU9->LED0001", "transport": "gate"},
            {"id": "zc", "kind": "cover", "name": "Roleta ZW", "grenton_id": "CLU9->ZWA0001", "transport": "gate", "tilt": True},
            {"id": "zd", "kind": "dimmer", "name": "Kinkiet ZW", "grenton_id": "CLU9->ZWA0002", "transport": "gate"},
            {"id": "ch", "kind": "led_channel", "name": "Biały", "grenton_id": "CLU9->LED0002", "transport": "gate", "channel": "w"},
        ],
    }
    entry = MockConfigEntry(domain="grenton", unique_id="iface1", title="iface1",
                            data={"ip_address": "x", "port": "9998", "pin": "1", "interface": INTERFACE},
                            options=options)
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

        led = hass.states.get("light.tasma")
        assert led.state == "on"
        assert led.attributes["color_mode"] == "rgb"
        assert led.attributes["rgb_color"] == (255, 128, 0)
        assert led.attributes["brightness"] == 128
        cover = hass.states.get("cover.roleta_zw")
        assert cover.attributes["current_position"] == 40
        assert "current_tilt_position" not in cover.attributes  # no tilt for Z-Wave
        assert hass.states.get("light.kinkiet_zw").attributes["brightness"] == 128
        assert hass.states.get("light.bialy").state == "off"

        def commands_since(n):
            return [c[2]["command"] for c in aioclient_mock.mock_calls[n:] if "command" in c[2]]

        n = aioclient_mock.call_count
        await hass.services.async_call("light", "turn_on",
                                       {"entity_id": "light.tasma", "rgb_color": [0, 0, 255], "brightness": 255}, blocking=True)
        assert commands_since(n) == [
            'CLU9:execute(0, "LED0001:execute(6,\\"#0000ff\\")")',
            'CLU9:execute(0, "LED0001:execute(12,0)")',
            'CLU9:execute(0, "LED0001:execute(0,1)")',
        ]
        n = aioclient_mock.call_count
        await hass.services.async_call("light", "turn_on", {"entity_id": "light.tasma", "white": 200}, blocking=True)
        assert commands_since(n) == ['CLU9:execute(0, "LED0001:execute(0,0)")', 'CLU9:execute(0, "LED0001:execute(12,200)")']
        n = aioclient_mock.call_count
        await hass.services.async_call("cover", "set_cover_position", {"entity_id": "cover.roleta_zw", "position": 70}, blocking=True)
        assert commands_since(n) == ['CLU9:execute(0, "ZWA0001:execute(7,70)")']
        n = aioclient_mock.call_count
        await hass.services.async_call("light", "turn_on", {"entity_id": "light.bialy", "brightness": 100}, blocking=True)
        assert commands_since(n) == ['CLU9:execute(0, "LED0002:execute(12,100)")']

        # Webhook push updates state without polling
        client = await hass_client_no_auth()
        resp = await client.post("/api/webhook/hook123", json=[
            {"id": "CLU9->ZWA0001", "index": 4, "value": 90},
            {"clu": "CLU9", "object": "LED0002", "index": 15, "value": 255},
            {"clu": "CLU9", "object": "UNKNOWN", "index": 0, "value": 1},
        ])
        assert resp.status == 200
        assert (await resp.json())["applied"] == 2
        await hass.async_block_till_done()
        assert hass.states.get("cover.roleta_zw").attributes["current_position"] == 90
        assert hass.states.get("light.bialy").state == "on"

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        resp = await client.post("/api/webhook/hook123", json={"clu": "CLU9", "object": "ZWA0001", "index": 4, "value": 1})
        assert resp.status == 200  # unregistered webhooks answer 200 but do nothing
        assert (await resp.text()) == ""


async def test_availability_connectivity_and_diagnostics(hass: HomeAssistant, aioclient_mock):
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse
    from custom_components.grenton.diagnostics import async_get_config_entry_diagnostics

    gate_up = {"ok": True}

    async def reply(method, url, data):
        if not gate_up["ok"]:
            return AiohttpClientMockResponse(method, url, status=500)
        out = {"g_status": "OK"}
        for k, lua in data.items():
            out[k] = 1 if k in ("status", "command") else _gate_values(lua)
        return AiohttpClientMockResponse(method, url, json=out)

    aioclient_mock.get(GATE_URL, side_effect=reply)
    interface = json.loads(json.dumps(INTERFACE))
    interface["pages"][0]["widgets"].append({"id": "bad1", "type": "VALUE_V2", "label": "Temp"})
    entry = MockConfigEntry(domain="grenton", unique_id="iface1", title="iface1",
                            data={"ip_address": "x", "port": "9998", "pin": "4321", "interface": interface},
                            options=OPTIONS)
    entry.add_to_hass(hass)
    api = "custom_components.grenton.domain.api.clu.GrentonCluApi"
    ping_ok = {"ok": True}

    async def ping(self):
        return ping_ok["ok"]

    async def register(self, keys):
        return [1 for _ in keys]

    with patch(f"{api}.connect", AsyncMock(return_value=True)), \
         patch(f"{api}.ping", ping), \
         patch(f"{api}.register_component_states", register), \
         patch(f"{api}.disconnect", AsyncMock()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data.coordinator
        gate = entry.runtime_data.gate_coordinator

        assert hass.states.get("binary_sensor.clu_parter").state == "on"
        assert hass.states.get("binary_sensor.grenton_gate_http").state == "on"
        assert hass.states.get("switch.lampa").state == "on"

        # CLU stops answering: unavailable after 3 missed pings, not before
        ping_ok["ok"] = False
        for _ in range(2):
            await coordinator._send_ping("CLU221000001")
        await hass.async_block_till_done()
        assert hass.states.get("switch.lampa").state == "on"
        await coordinator._send_ping("CLU221000001")
        await hass.async_block_till_done()
        assert hass.states.get("switch.lampa").state == "unavailable"
        assert hass.states.get("switch.pompa").state == "unavailable"
        assert hass.states.get("binary_sensor.clu_parter").state == "off"
        # Gate entities are independent of the UDP CLU
        assert hass.states.get("climate.termostat_salon").state == "heat"

        ping_ok["ok"] = True
        await coordinator._send_ping("CLU221000001")
        await hass.async_block_till_done()
        assert hass.states.get("switch.lampa").state == "on"
        assert hass.states.get("binary_sensor.clu_parter").state == "on"

        # Gate (REST) down -> its entities unavailable, connectivity off
        gate_up["ok"] = False
        await gate.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get("climate.termostat_salon").state == "unavailable"
        assert hass.states.get("binary_sensor.grenton_gate_http").state == "off"
        assert hass.states.get("switch.lampa").state == "on"
        gate_up["ok"] = True
        await gate.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get("binary_sensor.grenton_gate_http").state == "on"

        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["entry"]["data"]["pin"] == "**REDACTED**"
        assert diag["interface"]["encryption"]["key"] == "**REDACTED**"
        assert diag["clus"][0]["available"] is True
        assert [w["id"] for w in diag["skipped_widgets"]] == ["bad1"]
        assert any("unit" in e["loc"] for e in diag["skipped_widgets"][0]["errors"])
        assert diag["gate"]["last_update_success"] is True
        json.dumps(diag, default=str)

        await hass.config_entries.async_unload(entry.entry_id)
