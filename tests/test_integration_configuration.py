"""Native integration configuration and migration of removed device links."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from probatio import Invalid, to_field_list
from test_clu_scripts import make_clu, make_entry, make_hass
from test_on_off_configuration import coordinator, widget

from custom_components.homeassistant_grenton import _cleanup_orphans, async_setup_entry
from custom_components.homeassistant_grenton.domain.entities.clu import GrentonCluEntity
from custom_components.homeassistant_grenton.mappers.device_mapper import DeviceMapper
from custom_components.homeassistant_grenton.options_flow import GrentonOptionsFlow


def fields(result):
    return {
        field["name"]: field
        for field in to_field_list(
            result["data_schema"], custom_serializer=cv.custom_serializer
        )
    }


def test_integration_options_lists_all_widgets_and_preserves_sibling_configuration():
    async def run():
        coord = coordinator({"entities": {"other_0": {"entity_type": "light"}}})
        first = DeviceMapper.to_domain(widget(double=True), coord)
        other_dto = widget()
        other_dto.id = "other"
        second = DeviceMapper.to_domain(other_dto, coord)
        for device in (first, second):
            for entity in device.entities:
                entity.entity_id = "switch." + entity.unique_id
        coord.config_entry.runtime_data = SimpleNamespace(devices=[first, second])
        with patch.object(
            GrentonOptionsFlow,
            "config_entry",
            new_callable=PropertyMock,
            return_value=coord.config_entry,
        ):
            global_flow = GrentonOptionsFlow()
            result = await global_flow.async_step_entity_list()
            # HA cannot infer an initial value for integration-defined selectors.
            # The suggested empty string avoids that inference without choosing
            # a real entity or accepting an unselected form submission.
            assert fields(result)["entity"]["description"]["suggested_value"] == ""
            with pytest.raises(Invalid):
                result["data_schema"]({"entity": ""})
            assert (
                len(
                    fields(result)["entity"]["selector"]["grenton_entity"][
                        "include_entities"
                    ]
                )
                == 3
            )
            flow = GrentonOptionsFlow()
            result = await flow.async_step_entity_list({"entity": "switch.missing"})
            assert result["reason"] == "entity_not_found"
            # A valid selection keeps the existing three ON_OFF forms.
            result = await flow.async_step_entity_list({"entity": "switch.office_1"})
            assert result["step_id"] == "configure_on_off_state"
            result = await flow.async_step_configure_on_off_state(
                {"entity_type": "switch", "state": first.entities[1]._config["state"]}
            )
            on_draft = fields(result)["action_on"]["description"]["suggested_value"]
            result = await flow.async_step_configure_on_off_on_action(
                {"action_on": on_draft}
            )
            off_draft = fields(result)["action_off"]["description"]["suggested_value"]
            result = await flow.async_step_configure_on_off_off_action(
                {"action_off": off_draft}
            )
            assert result["type"] == "create_entry"
            assert set(result["data"]["entities"]) == {"other_0", "office_1"}
            assert result["data"]["entities"]["other_0"] == {"entity_type": "light"}

    asyncio.run(run())


def test_setup_does_not_attach_device_configuration_links(tmp_path):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        interface = {
            "id": "interface1",
            "version": 1,
            "name": "Home",
            "icon": "home",
            "theme": "GRENTON",
            "encryption": {"key": "00" * 16, "iv": "00" * 16},
            "clus": [
                {
                    "id": "clu1",
                    "serialNumber": "serial-clu1",
                    "name": "Main CLU",
                    "ip": "192.0.2.1",
                    "port": 1234,
                    "connectionType": "LOCAL_ONLY",
                }
            ],
            "pages": [],
            "pushNotifications": [],
        }
        entry = make_entry(interface=interface)
        coord = coordinator()
        coord.config_entry = entry
        coord.async_setup = AsyncMock()
        device = DeviceMapper.to_domain(widget(double=True), coord)
        hass.config_entries = SimpleNamespace(async_forward_entry_setups=AsyncMock())
        with (
            patch(
                "custom_components.homeassistant_grenton.GrentonCoordinator",
                return_value=coord,
            ),
            patch(
                "custom_components.homeassistant_grenton.DeviceMapper.from_mobile_interface",
                return_value=[device],
            ),
            patch("custom_components.homeassistant_grenton._cleanup_orphans"),
        ):
            await async_setup_entry(hass, entry)
        for entity in [*device.entities, *entry.runtime_data.clu_entities]:
            assert "configuration_url" not in entity.device_info

    asyncio.run(run())


@pytest.mark.parametrize(
    "configuration_url",
    [
        "homeassistant://grenton-configure/interface1/office",
        "https://example.com/device",
        None,
    ],
)
def test_reload_clears_legacy_widget_and_clu_links_without_changing_registry_data(
    tmp_path, configuration_url
):
    async def run():
        entry = make_entry()
        other_entry = make_entry("other_integration")
        hass = await make_hass(tmp_path, [entry, other_entry])
        await ar.async_load(hass, load_empty=True)
        area = ar.async_get(hass).async_create("Office")
        coord = coordinator()
        coord.config_entry = entry
        device = DeviceMapper.to_domain(widget(double=True), coord)
        controller = GrentonCluEntity(coord, make_clu("clu1"))
        registry = dr.async_get(hass)
        entities = er.async_get(hass)
        registered = []
        entity_ids = []
        for identifier, group in [
            (device.id, device.entities),
            (controller.unique_id, [controller]),
        ]:
            row = registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={("grenton", identifier)},
                name=identifier,
                configuration_url=configuration_url,
            )
            registry.async_update_device(
                row.id, name_by_user="My device", area_id=area.id
            )
            registered.append(row.id)
            for entity in group:
                entity_ids.append(
                    entities.async_get_or_create(
                        "sensor" if entity is controller else "switch",
                        "grenton",
                        entity.unique_id,
                        config_entry=entry,
                        device_id=row.id,
                    ).entity_id
                )
        unrelated = registry.async_get_or_create(
            config_entry_id=other_entry.entry_id,
            identifiers={("grenton", "other")},
            configuration_url="homeassistant://grenton-configure/other/other",
        )
        _cleanup_orphans(hass, entry, [device], [controller])
        expected = (
            None
            if (configuration_url or "").startswith(
                "homeassistant://grenton-configure/"
            )
            else configuration_url
        )
        for device_id in registered:
            row = registry.async_get(device_id)
            assert row.configuration_url == expected
            assert row.name_by_user == "My device"
            assert row.area_id == area.id
        assert all(
            entities.async_get(entity_id) is not None for entity_id in entity_ids
        )
        assert (
            registry.async_get(unrelated.id).configuration_url
            == unrelated.configuration_url
        )
        # Reloading again is harmless.
        _cleanup_orphans(hass, entry, [device], [controller])
        assert all(
            registry.async_get(device_id) is not None for device_id in registered
        )

    asyncio.run(run())
