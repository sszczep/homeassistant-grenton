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


def eid(hass, unique_id):
    """Entity id by unique id (HA may prefix ids with the area name)."""
    for domain in ("switch", "light", "cover", "climate", "sensor", "binary_sensor", "button"):
        if entity_id := er.async_get(hass).async_get_entity_id(domain, "grenton", unique_id):
            return entity_id
    raise AssertionError(f"no entity for {unique_id}")


def device(hass, identifier):
    reg = dr.async_get(hass)
    return next(d for d in reg.devices if ("grenton", identifier) in d.identifiers)


def st(hass, unique_id):
    return hass.states.get(eid(hass, unique_id))


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
        lamp = st(hass, "w1_0")
        assert lamp is not None and lamp.state == "on"
        # Manual UDP switch
        pump = st(hass, "manual_aaa")
        assert pump is not None and pump.state == "on"
        # Manual Gate thermostat
        climate = st(hass, "manual_bbb")
        assert climate is not None
        assert climate.state == "heat"
        assert climate.attributes["temperature"] == 21.5
        assert climate.attributes["current_temperature"] == 20.5

        dev_reg = dr.async_get(hass)
        pump_dev = device(hass, "manual_aaa")
        assert pump_dev.name == "Pompa"
        lamp_dev = device(hass, "w1")
        assert lamp_dev.name == "Lampa"
        area_reg = __import__("homeassistant.helpers.area_registry", fromlist=["x"]).async_get(hass)
        assert area_reg.async_get_area(lamp_dev.area_id).name == "Salon"
        assert area_reg.async_get_area(pump_dev.area_id).name == "Kotłownia"

        # UDP manual action -> unquoted numeric Lua
        await hass.services.async_call("switch", "turn_off", {"entity_id": eid(hass, "manual_aaa")}, blocking=True)
        assert executed[-1] == 'DOU0002:set(0,"0")'  # k911 rebuilds on/off actions from config (quoted like interface widgets)

        # Gate action -> wrapped in CLU:execute
        before = aioclient_mock.call_count
        await hass.services.async_call("climate", "set_temperature",
                                       {"entity_id": eid(hass, "manual_bbb"), "temperature": 22.5}, blocking=True)
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
        oid = entry.options["manual_objects"][0]["id"]
        assert st(hass, f"manual_{oid}") is not None  # reloaded with new object

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
        assert er.async_get(hass).async_get_entity_id("switch", "grenton", f"manual_{oid}") is None
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
        lamp_section = next(str(k) for k in result["data_schema"].schema if "w1" in str(k))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"area": "Pokój dzienny", lamp_section: {"Name": "Żyrandol"}})
        assert result["type"] == FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert st(hass, "w1_0").attributes["friendly_name"] == "Żyrandol"
        dev = device(hass, "w1")
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

        led = st(hass, "manual_led")
        assert led.state == "on"
        assert led.attributes["color_mode"] == "rgb"
        assert led.attributes["rgb_color"] == (255, 128, 0)
        assert led.attributes["brightness"] == 128
        cover = st(hass, "manual_zc")
        assert cover.attributes["current_position"] == 40
        assert "current_tilt_position" not in cover.attributes  # no tilt for Z-Wave
        assert st(hass, "manual_zd").attributes["brightness"] == 128
        assert st(hass, "manual_ch").state == "off"

        def commands_since(n):
            return [c[2]["command"] for c in aioclient_mock.mock_calls[n:] if "command" in c[2]]

        n = aioclient_mock.call_count
        await hass.services.async_call("light", "turn_on",
                                       {"entity_id": eid(hass, "manual_led"), "rgb_color": [0, 0, 255], "brightness": 255}, blocking=True)
        assert commands_since(n) == [
            'CLU9:execute(0, "LED0001:execute(6,\\"#0000ff\\")")',
            'CLU9:execute(0, "LED0001:execute(12,0)")',
            'CLU9:execute(0, "LED0001:execute(0,1)")',
        ]
        n = aioclient_mock.call_count
        await hass.services.async_call("light", "turn_on", {"entity_id": eid(hass, "manual_led"), "white": 200}, blocking=True)
        assert commands_since(n) == ['CLU9:execute(0, "LED0001:execute(0,0)")', 'CLU9:execute(0, "LED0001:execute(12,200)")']
        n = aioclient_mock.call_count
        await hass.services.async_call("cover", "set_cover_position", {"entity_id": eid(hass, "manual_zc"), "position": 70}, blocking=True)
        assert commands_since(n) == ['CLU9:execute(0, "ZWA0001:execute(7,70)")']
        n = aioclient_mock.call_count
        await hass.services.async_call("light", "turn_on", {"entity_id": eid(hass, "manual_ch"), "brightness": 100}, blocking=True)
        assert commands_since(n) == ['CLU9:execute(0, "LED0002:execute(12,\\"100\\")")']

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
        assert st(hass, "manual_zc").attributes["current_position"] == 90
        assert st(hass, "manual_ch").state == "on"

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

        assert st(hass, "connectivity_gate_http").state == "on"
        assert st(hass, "w1_0").state == "on"

        # Gate (REST) down -> its entities unavailable, connectivity off
        gate_up["ok"] = False
        await gate.async_refresh()
        await hass.async_block_till_done()
        assert st(hass, "manual_bbb").state == "unavailable"
        assert st(hass, "connectivity_gate_http").state == "off"
        gate_up["ok"] = True
        await gate.async_refresh()
        await hass.async_block_till_done()
        assert st(hass, "connectivity_gate_http").state == "on"

        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["entry"]["data"]["pin"] == "**REDACTED**"
        assert diag["interface"]["encryption"]["key"] == "**REDACTED**"
        assert diag["clus"][0]["id"] == "CLU221000001"
        assert [w["id"] for w in diag["skipped_widgets"]] == ["bad1"]
        assert any("unit" in e["loc"] for e in diag["skipped_widgets"][0]["errors"])
        assert diag["gate"]["last_update_success"] is True
        json.dumps(diag, default=str)

        await hass.config_entries.async_unload(entry.entry_id)


VALUE_V2 = {
    "id": "temp1", "type": "VALUE_V2", "label": "Temperatura", "icon": "t", "unit": "UNKNOWN",
    "valueType": "FLOAT", "precision": 1,
    "object": {"value": {"callType": "ATTRIBUTE", "cluId": "CLU221000001", "objectName": "ONW0001", "index": "0"}},
}
VALUE_DOUBLE = {
    "id": "pair1", "type": "VALUE_DOUBLE",
    "componentLeft": {"label": "Wilgotność", "icon": "h", "unit": "UNKNOWN", "valueType": "FLOAT", "precision": 0,
                      "object": {"value": {"callType": "ATTRIBUTE", "cluId": "CLU221000001", "objectName": "ONW0002", "index": "0"}}},
    "componentRight": {"label": "Ciśnienie", "icon": "p", "unit": "UNKNOWN", "valueType": "FLOAT", "precision": 0,
                       "object": {"value": {"callType": "ATTRIBUTE", "cluId": "CLU221000001", "objectName": "ONW0003", "index": "0"}}},
}


async def _flow_until_page(hass, interface):
    om = "custom_components.grenton.config_flow.GrentonObjectManagerApi"

    class FakeOM:
        def __init__(self, url): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def fetch_mobile_interface(self, pin): return interface

    with patch(om, FakeOM):
        result = await hass.config_entries.flow.async_init("grenton", context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"ip_address": "1.2.3.4", "port": "9998", "pin": "1"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"customize_names": True})
    return result


async def test_import_entity_names_units_precision(hass: HomeAssistant):
    hass.config.language = "pl"
    interface = json.loads(json.dumps(INTERFACE))
    interface["pages"][0]["widgets"] += [VALUE_V2, VALUE_DOUBLE]
    api = "custom_components.grenton.domain.api.clu.GrentonCluApi"

    async def register(self, keys):
        return [21.456 for _ in keys]

    with patch(f"{api}.connect", AsyncMock(return_value=True)), \
         patch(f"{api}.ping", AsyncMock(return_value=True)), \
         patch(f"{api}.register_component_states", register), \
         patch(f"{api}.disconnect", AsyncMock()):
        result = await _flow_until_page(hass, interface)
        assert result["step_id"] == "page_names"
        sections = {str(k): v for k, v in result["data_schema"].schema.items() if str(k) != "area"}
        keys = list(sections)
        temp_key = next(k for k in keys if "temp1" in k)
        pair_key = next(k for k in keys if "pair1" in k)
        lamp_key = next(k for k in keys if "w1" in k)
        pair_fields = [str(k) for k in sections[pair_key].schema.schema]
        assert pair_fields[0] == "Nazwa urządzenia"
        assert "Wilgotność: nazwa" in pair_fields and "Ciśnienie: jednostka" in pair_fields

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {
            "area": "Salon",
            lamp_key: {"Nazwa": "Lampa sufitowa"},
            temp_key: {"Nazwa": "Temperatura salon", "klasa urządzenia": "temperature",
                       "jednostka": "°C", "dokładność (miejsca po przecinku)": 1},
            pair_key: {"Nazwa urządzenia": "Czujnik klimatu",
                       "Wilgotność: nazwa": "Wilgotność salon", "Wilgotność: jednostka": "%",
                       "Wilgotność: klasa urządzenia": "humidity",
                       "Ciśnienie: nazwa": "Wilgotność · Ciśnienie Ciśnienie",  # prefilled default kept
                       "Ciśnienie: jednostka": "hPa",
                       "Ciśnienie: dokładność (miejsca po przecinku)": 0},
        })
        assert result["type"] == FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        entry = hass.config_entries.async_entries("grenton")[0]

        assert st(hass, "w1_0").attributes["friendly_name"] == "Lampa sufitowa"
        temp = st(hass, "temp1_0")
        assert temp.attributes["friendly_name"] == "Temperatura salon"
        assert temp.attributes["unit_of_measurement"] == "°C"
        assert temp.attributes["device_class"] == "temperature"
        # Realtime values need a CLU report (mocked away); precision is checked in the registry
        def precision(uid):
            reg = er.async_get(hass)
            return reg.async_get(eid(hass, uid)).options["sensor"]["suggested_display_precision"]
        assert precision("temp1_0") == 1
        uids = [e.unique_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)]
        hum_uid = next(u for u in uids if u.startswith("pair1") and u.endswith("0"))
        pres_uid = next(u for u in uids if u.startswith("pair1") and u.endswith("1"))
        hum, pres = st(hass, hum_uid), st(hass, pres_uid)
        assert hum.attributes["friendly_name"] == "Wilgotność salon"
        assert hum.attributes["unit_of_measurement"] == "%"
        assert hum.attributes["device_class"] == "humidity"
        # Unchanged name keeps the default (device name + label) with the custom device name
        assert pres.attributes["friendly_name"] == "Czujnik klimatu Ciśnienie"
        assert pres.attributes["unit_of_measurement"] == "hPa"
        assert precision(pres_uid) == 0
        assert device(hass, "pair1").name == "Czujnik klimatu"
        assert entry.options["entity_overrides"][hum_uid] == {"name": "Wilgotność salon"}
        assert entry.options["entity_overrides"][pres_uid] == {"precision": 0}

        # Same form later in the options; current values are prefilled
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert "entity_names" in result["menu_options"]
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "entity_names"})
        assert result["step_id"] == "entity_names"
        sections = {str(k): v for k, v in result["data_schema"].schema.items() if str(k) != "area"}
        temp_fields = {str(k): k for k in sections[temp_key].schema.schema}
        assert temp_fields["Nazwa"].default() == "Temperatura salon"
        result = await hass.config_entries.options.async_configure(result["flow_id"], {
            "area": "Salon",
            temp_key: {"Nazwa": "Temp. salon", "klasa urządzenia": "temperature", "jednostka": "°C",
                       "dokładność (miejsca po przecinku)": 2},
        })
        assert result["type"] == FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        temp = st(hass, "temp1_0")
        assert temp.attributes["friendly_name"] == "Temp. salon"
        assert precision("temp1_0") == 2
        await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_keeps_settings_and_refreshes_interface(hass: HomeAssistant, aioclient_mock):
    """Reconfigure: new widgets appear, removed ones go, own settings survive."""
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

    async def reply(method, url, data):
        out = {"g_status": "OK"}
        for k, lua in data.items():
            out[k] = 1 if k in ("status", "command") else _gate_values(lua)
        return AiohttpClientMockResponse(method, url, json=out)

    aioclient_mock.get(GATE_URL, side_effect=reply)
    old_interface = json.loads(json.dumps(INTERFACE))
    old_interface["pages"][0]["widgets"].append(VALUE_V2)
    entry = MockConfigEntry(
        domain="grenton", unique_id="iface1", title="iface1",
        data={"ip_address": "1.2.3.4", "port": "9998", "pin": "1", "interface": old_interface,
              "device_names": {"w1": "Lampa sufitowa"}, "page_areas": {"Salon": "Salon"}},
        options={**OPTIONS, "entity_overrides": {"temp1_0": {"precision": 1}}},
    )
    entry.add_to_hass(hass)

    new_interface = json.loads(json.dumps(INTERFACE))  # VALUE_V2 removed ...
    new_interface["pages"][0]["widgets"].append(VALUE_DOUBLE)  # ... VALUE_DOUBLE added

    api = "custom_components.grenton.domain.api.clu.GrentonCluApi"
    om = "custom_components.grenton.config_flow.GrentonObjectManagerApi"

    class FakeOM:
        def __init__(self, url): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def fetch_mobile_interface(self, pin): return new_interface

    async def register(self, keys):
        return [1 for _ in keys]

    with patch(om, FakeOM), \
         patch(f"{api}.connect", AsyncMock(return_value=True)), \
         patch(f"{api}.ping", AsyncMock(return_value=True)), \
         patch(f"{api}.register_component_states", register), \
         patch(f"{api}.disconnect", AsyncMock()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert st(hass, "temp1_0") is not None

        result = await entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "reconfigure"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"ip_address": "1.2.3.4", "port": "9998", "pin": "1"})
        assert result["step_id"] == "naming"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"customize_names": True})
        assert result["step_id"] == "page_names"
        # Current custom device name is prefilled
        lamp_key = next(k for k in result["data_schema"].schema if "w1" in str(k))
        pair_key = next(str(k) for k in result["data_schema"].schema if "pair1" in str(k))
        lamp_fields = {str(k): k for k in result["data_schema"].schema[lamp_key].schema.schema}
        assert lamp_fields["Name"].default() == "Lampa sufitowa"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {
            "area": "Salon",
            str(lamp_key): {"Name": "Lampa sufitowa"},
            pair_key: {"Device name": "Klimat"},
        })
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        await hass.async_block_till_done()

        # Interface refreshed: removed widget gone, new one present
        reg = er.async_get(hass)
        assert reg.async_get_entity_id("sensor", "grenton", "temp1_0") is None
        assert any(e.unique_id.startswith("pair1") for e in er.async_entries_for_config_entry(reg, entry.entry_id))
        assert device(hass, "pair1").name == "Klimat"
        assert st(hass, "w1_0").attributes["friendly_name"] == "Lampa sufitowa"
        # Manual objects and Gate settings survive the reconfigure
        assert st(hass, "manual_aaa") is not None
        assert st(hass, "manual_bbb").state == "heat"
        assert entry.options["gate"]["url"] == GATE_URL
        assert entry.data["pin"] == "1"
        await hass.config_entries.async_unload(entry.entry_id)


def _scene_action(script, event="CLICK", value=""):
    return {"callType": "SCRIPT", "event": event, "cluId": "CLU221000001", "objectName": script, "value": value}


SCENE_DOUBLE_SHAPES = {
    # like ON_OFF_DOUBLE: two rows
    "rows": {"id": "sd1", "type": "SCENE_DOUBLE", "components": [
        {"type": "BUTTON_MONOSTABLE", "label": "Otwórz", "rowId": 0, "unit": "UNKNOWN", "actions": [_scene_action("bramaOtworz")]},
        {"type": "BUTTON_MONOSTABLE", "label": "Zamknij", "rowId": 1, "unit": "UNKNOWN", "actions": [_scene_action("bramaZamknij")]},
    ]},
    # like VALUE_DOUBLE: left/right
    "sides": {"id": "sd1", "type": "SCENE_DOUBLE",
              "componentLeft": {"label": "Otwórz", "actions": [_scene_action("bramaOtworz")]},
              "componentRight": {"label": "Zamknij", "actions": [_scene_action("bramaZamknij")]}},
    # one row with two actions and unknown per-side event names
    "one_row": {"id": "sd1", "type": "SCENE_DOUBLE", "label": "Brama", "components": [
        {"label": "Brama", "rowId": 0, "actions": [_scene_action("bramaOtworz", "CLICK_LEFT"),
                                                   _scene_action("bramaZamknij", "CLICK_RIGHT")]},
    ]},
}


import pytest  # noqa: E402


@pytest.mark.parametrize("shape", list(SCENE_DOUBLE_SHAPES))
async def test_scene_double_buttons(hass: HomeAssistant, shape):
    interface = json.loads(json.dumps(INTERFACE))
    interface["pages"][0]["widgets"].append(SCENE_DOUBLE_SHAPES[shape])
    entry = MockConfigEntry(domain="grenton", unique_id="iface1", title="iface1",
                            data={"ip_address": "x", "port": "9998", "pin": "1", "interface": interface})
    entry.add_to_hass(hass)
    api = "custom_components.grenton.domain.api.clu.GrentonCluApi"
    executed = []

    async def register(self, keys):
        return [0 for _ in keys]

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

        buttons = [e for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
                   if e.domain == "button" and e.unique_id.startswith("sd1")]
        assert len(buttons) == 2, [b.unique_id for b in buttons]
        for button in buttons:
            await hass.services.async_call("button", "press", {"entity_id": button.entity_id}, blocking=True)
        assert sorted(executed) == ["bramaOtworz()", "bramaZamknij()"]
        names = sorted(hass.states.get(b.entity_id).attributes["friendly_name"] for b in buttons)
        if shape == "one_row":
            assert names == ["Brama Click left", "Brama Click right"]
        else:
            assert names == ["Otwórz · Zamknij Otwórz", "Otwórz · Zamknij Zamknij"]
        await hass.config_entries.async_unload(entry.entry_id)


async def test_import_from_grenton_objects_takes_over_entity_ids(hass: HomeAssistant, aioclient_mock):
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

    async def reply(method, url, data):
        out = {"g_status": "OK"}
        for k, lua in data.items():
            out[k] = 1 if k in ("status", "command") else _gate_values(lua)
        return AiohttpClientMockResponse(method, url, json=out)

    aioclient_mock.get(GATE_URL, side_effect=reply)
    reg = er.async_get(hass)
    area = __import__("homeassistant.helpers.area_registry", fromlist=["x"]).async_get(hass).async_create("Kotłownia")

    def old_object(title, data, platform, object_id, unique_id, **registry_kwargs):
        entry = MockConfigEntry(domain="grenton_objects", title=title,
                                data={"api_endpoint": "10.0.0.50/HAlistener", "auto_update": True,
                                      "update_interval": 10, **data})
        entry.add_to_hass(hass)
        ent = reg.async_get_or_create(platform, "grenton_objects", unique_id, config_entry=entry,
                                      suggested_object_id=object_id, original_name=title)
        if registry_kwargs:
            ent = reg.async_update_entity(ent.entity_id, **registry_kwargs)
        return entry, ent

    _, pump = old_object("Pompa", {"grenton_id": "CLU221000001->DOU0002", "name": "Pompa"},
                         "switch", "pompa_cwu", "grenton_DOU0002", name="Pompa CWU", area_id=area.id, icon="mdi:pump")
    _, therm = old_object("Termostat", {"grenton_id": "CLU221000009->THE0001", "name": "Termostat"},
                          "climate", "termostat_salon", "grenton_THE0001")
    _, temp = old_object("Temperatura", {"grenton_id": "CLU221000009->tempZewn", "name": "Temperatura",
                                         "grenton_type": "DEFAULT_SENSOR", "device_class": "temperature",
                                         "unit_of_measurement": "°C", "state_class": "measurement"},
                         "sensor", "temperatura_zewn", "grenton_tempZewn")
    old_object("Zmienna gate", {"grenton_id": "gateVar", "name": "Zmienna gate"},
               "sensor", "zmienna_gate", "grenton_gateVar")

    entry = MockConfigEntry(domain="grenton", unique_id="iface1", title="iface1",
                            data={"ip_address": "x", "port": "9998", "pin": "1", "interface": INTERFACE})
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

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert "import_grenton_objects" in result["menu_options"]
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "import_grenton_objects"})
        assert result["step_id"] == "import_grenton_objects"
        assert "gateVar" in result["description_placeholders"]["skipped"]
        defaults = [k for k in result["data_schema"].schema if str(k) == "objects"][0].default()
        assert len(defaults) == 3
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"objects": defaults, "prefer_udp": True, "take_over": True})
        assert result["type"] == FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

        # Old entries gone, only the Gate-variable one stays
        assert [e.title for e in hass.config_entries.async_entries("grenton_objects")] == ["Zmienna gate"]
        # Same entity_ids, now owned by this integration
        for old in (pump, therm, temp):
            new = reg.async_get(old.entity_id)
            assert new is not None and new.platform == "grenton", old.entity_id
            assert new.config_entry_id == entry.entry_id
        new_pump = reg.async_get(pump.entity_id)
        assert new_pump.name == "Pompa CWU" and new_pump.icon == "mdi:pump" and new_pump.area_id == area.id

        # Transport: CLU in interface -> UDP, others -> Gate (URL taken over)
        objects = {o["name"]: o for o in entry.options["manual_objects"]}
        assert objects["Pompa"]["transport"] == "udp"
        assert objects["Termostat"]["transport"] == "gate"
        assert objects["Temperatura"]["variable"] is True
        assert entry.options["gate"]["url"] == GATE_URL

        # Entities work under the old ids
        assert hass.states.get(pump.entity_id).state == "on"
        assert hass.states.get(therm.entity_id).state == "heat"
        temp_state = hass.states.get(temp.entity_id)
        assert temp_state.attributes["unit_of_measurement"] == "°C"
        assert temp_state.attributes["device_class"] == "temperature"
        await hass.services.async_call("switch", "turn_off", {"entity_id": pump.entity_id}, blocking=True)
        assert executed[-1] == 'DOU0002:set(0,"0")'
        await hass.config_entries.async_unload(entry.entry_id)


async def test_thermostat_v1_widgets_from_real_interface(hass: HomeAssistant, caplog):
    """Six THERMOSTAT (v1) widgets from a real interface become climate entities."""
    import pathlib
    interface = json.loads((pathlib.Path(__file__).parent / "fixtures" / "interface_thermostat_v1.json").read_text())
    entry = MockConfigEntry(domain="grenton", unique_id=interface["id"], title=interface["id"],
                            data={"ip_address": "x", "port": "9998", "pin": "1", "interface": interface})
    entry.add_to_hass(hass)
    api = "custom_components.grenton.domain.api.clu.GrentonCluApi"
    executed = []
    # state on, mode 1, current 21.3, target 22, output 1 (heating), min 18, max 24
    by_index = {"6": 1, "8": 1, "14": 21.3, "12": 22.0, "13": 1, "10": 18.0, "11": 24.0, "9": ""}

    async def register(self, keys):
        return [by_index.get(str(getattr(k, "name", "")), 0) for k in keys]

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

        reg = er.async_get(hass)
        climates = [e for e in er.async_entries_for_config_entry(reg, entry.entry_id) if e.domain == "climate"]
        assert len(climates) == 6
        names = sorted(hass.states.get(e.entity_id).attributes["friendly_name"] for e in climates)
        assert "Ania" in names
        assert device(hass, "wrx8in4S").model == "THERMOSTAT"
        # Headers are not reported as skipped widgets
        assert "Skipping widget type HEADER" not in caplog.text
        assert "Skipping widget type THERMOSTAT" not in caplog.text

        ania = next(e for e in climates if hass.states.get(e.entity_id).attributes["friendly_name"] == "Ania")
        await hass.services.async_call("climate", "set_temperature",
                                       {"entity_id": ania.entity_id, "temperature": 23}, blocking=True)
        assert any(p.startswith("THE1270:set(3,") for p in executed), executed

        from custom_components.grenton.diagnostics import async_get_config_entry_diagnostics
        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["skipped_widgets"] == []
        await hass.config_entries.async_unload(entry.entry_id)


async def test_thermostat_schedule_shows_target_and_change_switches_to_manual(hass: HomeAssistant):
    import pathlib
    interface = json.loads((pathlib.Path(__file__).parent / "fixtures" / "interface_thermostat_v1.json").read_text())
    entry = MockConfigEntry(domain="grenton", unique_id=interface["id"], title=interface["id"],
                            data={"ip_address": "x", "port": "9998", "pin": "1", "interface": interface})
    entry.add_to_hass(hass)
    api = "custom_components.grenton.domain.api.clu.GrentonCluApi"
    executed = []
    # state on, mode 2 = schedule, target from schedule 20.5
    by_index = {"6": 1, "8": 2, "14": 19.8, "12": 20.5, "13": 0, "10": 10.0, "11": 30.0, "9": ""}

    async def register(self, keys):
        return [by_index.get(str(getattr(k, "name", "")), 0) for k in keys]

    async def execute(self, action):
        executed.append(GrentonCluApiActionRequest.from_action(action).payload)
        return True

    with patch(f"{api}.connect", AsyncMock(return_value=True)), \
         patch(f"{api}.ping", AsyncMock(return_value=True)), \
         patch(f"{api}.register_component_states", register), \
         patch(f"{api}.fetch_component_states", register), \
         patch(f"{api}.execute_action", execute), \
         patch(f"{api}.disconnect", AsyncMock()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        climate_id = eid(hass, "wrx8in4S_climate")
        # Temperatures are slow reads; trigger one instead of waiting for the timer
        coordinator = entry.runtime_data.coordinator
        await coordinator._send_slow_poll("CLU221005591")
        await hass.async_block_till_done()
        state = hass.states.get(climate_id)
        assert state.state == "auto"
        assert state.attributes["temperature"] == 20.5  # visible on the card in schedule mode
        target = st(hass, "wrx8in4S_target_temperature")
        assert target is not None and target.attributes["unit_of_measurement"] == "°C"

        await hass.services.async_call("climate", "set_temperature",
                                       {"entity_id": climate_id, "temperature": 22}, blocking=True)
        assert executed[0].startswith("THE1270:set(3,")
        assert 'THE1270:set(8,"0")' in executed  # manual mode
        assert executed[-1] == 'THE1270:set(6,"1")'
        await hass.config_entries.async_unload(entry.entry_id)



async def test_schedule_card_module_is_served(hass: HomeAssistant, hass_client):
    """The dashboard card is registered as a frontend module with a hashed URL."""
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, "http", {})
    # The frontend package is not installed in tests; record the module URLs instead
    hass.config.components.add("frontend")
    loaded = []
    entry = MockConfigEntry(domain="grenton", unique_id="iface1", title="iface1",
                            data={"ip_address": "x", "port": "9998", "pin": "1", "interface": INTERFACE})
    entry.add_to_hass(hass)
    api = "custom_components.grenton.domain.api.clu.GrentonCluApi"

    async def register(self, keys, **kwargs):
        return [0 for _ in keys]

    with patch(f"{api}.connect", AsyncMock(return_value=True)), \
         patch(f"{api}.ping", AsyncMock(return_value=True)), \
         patch(f"{api}.register_component_states", register), \
         patch(f"{api}.disconnect", AsyncMock()), \
         patch("homeassistant.components.frontend.add_extra_js_url", lambda hass, url: loaded.append(url)), \
         patch("homeassistant.components.frontend.remove_extra_js_url", lambda hass, url: None):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        # The card ships inside the integration's frontend module
        url = hass.data["grenton"]["scene_editor_url"]
        assert url in loaded
        client = await hass_client()
        response = await client.get(url)
        assert response.status == 200
        assert "grenton-schedule-card" in await response.text()
        await hass.config_entries.async_unload(entry.entry_id)
