"""Load the scene selectors in Home Assistant's frontend."""

import asyncio
import hashlib
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_register_scene_editor(
    hass: HomeAssistant, *, notify_clients: bool = False
) -> None:
    """Register the module once, with a content-based URL to avoid stale UI."""
    if "frontend" not in hass.config.components:
        return
    from homeassistant.components import frontend
    from homeassistant.components.http import StaticPathConfig

    data = hass.data.setdefault(DOMAIN, {})
    lock = data.setdefault("scene_editor_lock", asyncio.Lock())
    async with lock:
        path = Path(__file__).parent / "frontend" / "scene-editor.js"
        digest = await hass.async_add_executor_job(
            lambda: hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        )
        url = f"/grenton/scene-editor-{digest}.js"
        previous_url = data.get("scene_editor_url")
        if previous_url == url:
            if notify_clients:
                # A browser left open across a HA restart may still have the
                # previous module. Reannounce the URL through HA's resource feed.
                frontend.add_extra_js_url(hass, url)
            return
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(url, str(path), True),
            ]
        )
        frontend.add_extra_js_url(hass, url)
        if previous_url is not None:
            frontend.remove_extra_js_url(hass, previous_url)
        data["scene_editor_url"] = url
