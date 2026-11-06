"""Check that the editor's JavaScript is actually registered for the UI."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant import components

from custom_components.homeassistant_grenton.frontend import async_register_scene_editor
from custom_components.homeassistant_grenton.options_flow import GrentonOptionsFlow


def test_scene_editor_assets_register_once_for_multiple_config_entries():
    frontend = SimpleNamespace(
        add_extra_js_url=Mock(), async_register_built_in_panel=Mock()
    )
    hass = SimpleNamespace(
        config=SimpleNamespace(components={"frontend"}),
        data={},
        http=SimpleNamespace(async_register_static_paths=AsyncMock()),
        async_add_executor_job=AsyncMock(side_effect=lambda job: job()),
    )

    async def run():
        with patch.object(components, "frontend", frontend, create=True):
            await asyncio.gather(
                async_register_scene_editor(hass),
                async_register_scene_editor(hass),
            )

    asyncio.run(run())
    hass.http.async_register_static_paths.assert_awaited_once()
    (static_path,) = hass.http.async_register_static_paths.await_args.args[0]
    assert static_path.url_path.startswith("/grenton/scene-editor-")
    assert static_path.url_path.endswith(".js")
    assert Path(static_path.path).is_file()
    assert static_path.cache_headers is True
    frontend.add_extra_js_url.assert_called_once_with(hass, static_path.url_path)
    assert hass.data["grenton"]["scene_editor_url"] == static_path.url_path
    frontend.async_register_built_in_panel.assert_not_called()


def test_headless_home_assistant_does_not_load_frontend_assets():
    hass = SimpleNamespace(config=SimpleNamespace(components=set()))
    asyncio.run(async_register_scene_editor(hass))


def test_configuration_registers_selectors_if_frontend_was_unavailable_at_startup():
    hass = SimpleNamespace(
        config=SimpleNamespace(components=set()),
        data={},
        http=SimpleNamespace(async_register_static_paths=AsyncMock()),
        async_add_executor_job=AsyncMock(side_effect=lambda job: job()),
    )
    frontend = SimpleNamespace(add_extra_js_url=Mock())

    async def run():
        await async_register_scene_editor(hass)
        hass.http.async_register_static_paths.assert_not_awaited()
        hass.config.components.add("frontend")
        flow = GrentonOptionsFlow()
        flow.hass = hass
        with patch.object(components, "frontend", frontend, create=True):
            result = await flow.async_step_init()
        assert result["type"] == "menu"
        assert "scene_editor_url" in hass.data["grenton"]

    asyncio.run(run())
    hass.http.async_register_static_paths.assert_awaited_once()
    frontend.add_extra_js_url.assert_called_once()


def test_changed_assets_replace_cached_module_url_without_duplicate_registration():
    frontend = SimpleNamespace(add_extra_js_url=Mock(), remove_extra_js_url=Mock())
    hass = SimpleNamespace(
        config=SimpleNamespace(components={"frontend"}),
        data={"grenton": {"scene_editor_url": "/grenton/scene-editor-old.js"}},
        http=SimpleNamespace(async_register_static_paths=AsyncMock()),
        async_add_executor_job=AsyncMock(side_effect=lambda job: job()),
    )

    async def run():
        with patch.object(components, "frontend", frontend, create=True):
            await asyncio.gather(
                async_register_scene_editor(hass), async_register_scene_editor(hass)
            )

    asyncio.run(run())
    url = hass.data["grenton"]["scene_editor_url"]
    assert url != "/grenton/scene-editor-old.js"
    hass.http.async_register_static_paths.assert_awaited_once()
    frontend.add_extra_js_url.assert_called_once_with(hass, url)
    frontend.remove_extra_js_url.assert_called_once_with(
        hass, "/grenton/scene-editor-old.js"
    )


def test_opening_configuration_reannounces_assets_to_existing_browser_tabs():
    frontend = SimpleNamespace(add_extra_js_url=Mock())
    hass = SimpleNamespace(
        config=SimpleNamespace(components={"frontend"}),
        data={},
        http=SimpleNamespace(async_register_static_paths=AsyncMock()),
        async_add_executor_job=AsyncMock(side_effect=lambda job: job()),
    )

    async def run():
        with patch.object(components, "frontend", frontend, create=True):
            await async_register_scene_editor(hass)
            flow = GrentonOptionsFlow()
            flow.hass = hass
            await flow.async_step_init()

    asyncio.run(run())
    hass.http.async_register_static_paths.assert_awaited_once()
    assert frontend.add_extra_js_url.call_count == 2
    assert (
        frontend.add_extra_js_url.call_args_list[0]
        == frontend.add_extra_js_url.call_args_list[1]
    )
