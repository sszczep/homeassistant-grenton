"""Native CLU menu headers render without the context used by descriptions."""

import asyncio
import json
from pathlib import Path

import pytest
from test_clu_scripts import make_entry, make_hass
from test_clu_variables import configure_manager


@pytest.mark.parametrize("language", ["en", "pl"])
@pytest.mark.parametrize("clu_id,name", [("clu1", "Main"), ("clu2", "Gate")])
def test_clu_menu_header_needs_no_placeholders_and_description_identifies_selection(
    tmp_path, language, clu_id, name
):
    async def run():
        entry = make_entry(
            interface={
                "clus": [
                    {"id": "clu1", "name": "Main"},
                    {"id": "clu2", "name": "Gate"},
                ]
            }
        )
        hass = await make_hass(tmp_path, [entry])
        manager = configure_manager(hass, entry)
        form = await manager.async_init(entry.entry_id)
        form = await manager.async_configure(
            form["flow_id"], {"next_step_id": "clu_read_settings"}
        )
        menu = await manager.async_configure(form["flow_id"], {"clu_id": clu_id})
        assert menu["type"] == "menu"
        assert menu["step_id"] == "clu_configuration"
        translations = json.loads(
            (
                Path(__file__).parents[1]
                / f"custom_components/homeassistant_grenton/translations/{language}.json"
            ).read_text()
        )["options"]["step"][menu["step_id"]]
        # HA's renderMenuHeader localizes without description_placeholders;
        # only renderMenuDescription receives them. A title placeholder would
        # reproduce the frontend's MISSING_VALUE failure here.
        assert (
            translations["title"].format()
            == {
                "en": "Configure CLU",
                "pl": "Konfiguruj CLU",
            }[language]
        )
        assert (
            translations["description"].format(**menu["description_placeholders"])
            == name
        )
        assert set(menu["menu_options"]) == {"clu_read_interval", "clu_variables"}
        manager.async_abort(menu["flow_id"])
        await hass.async_stop()

    asyncio.run(run())
