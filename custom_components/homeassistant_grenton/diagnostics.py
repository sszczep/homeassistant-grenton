"""Diagnostics for the Grenton integration (#5).

Contains the mobile interface JSON with secrets redacted, the reason every
skipped widget failed validation, CLU connection state and the manual
objects. PIN, encryption key/IV and the webhook id are redacted; IP addresses
are kept because they are needed to debug connectivity.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .dto.page import DECORATIVE_WIDGET_TYPES, validate_widget
from .integration_config import GrentonConfigEntry

TO_REDACT = {"pin", "key", "iv", "webhook_id", "password", "token"}


def _skipped_widgets(interface: dict[str, Any]) -> list[dict[str, Any]]:
    skipped: list[dict[str, Any]] = []
    for page in interface.get("pages", []) or []:
        for item in page.get("widgets", []) or []:
            if isinstance(item, dict) and item.get("type") in DECORATIVE_WIDGET_TYPES:
                continue
            widget, error = validate_widget(item)
            if widget is None and error is not None:
                skipped.append({
                    "page": page.get("name"),
                    "type": item.get("type") if isinstance(item, dict) else None,
                    "id": item.get("id") if isinstance(item, dict) else None,
                    "errors": [
                        {"loc": ".".join(str(p) for p in e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
                        for e in error.errors()
                    ],
                })
    return skipped


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: GrentonConfigEntry) -> dict[str, Any]:
    interface: dict[str, Any] = dict(entry.data.get("interface") or {})
    runtime = getattr(entry, "runtime_data", None)

    clus: list[dict[str, Any]] = []
    devices: list[dict[str, Any]] = []
    gate: dict[str, Any] | None = None
    if runtime is not None:
        coordinator = runtime.coordinator
        for clu in coordinator.clus:
            health = coordinator.connection_health.get(clu.id)
            clus.append({
                "id": clu.id,
                "name": clu.name,
                "ip": clu.ip,
                "port": clu.port,
                "connected": health.connected if health else None,
                "last_seen": health.last_seen.isoformat() if health and health.last_seen else None,
                "request_timeouts": health.request_timeouts if health else None,
            })
        for device in runtime.devices:
            devices.append({
                "id": device.id,
                "type": device.type,
                "name": device.name,
                "entities": [
                    {"unique_id": e.unique_id, "label": e.label, "class": type(e).__name__, "available": e.available}
                    for e in device.entities
                ],
            })
        if runtime.gate_coordinator is not None:
            gate_coordinator = runtime.gate_coordinator
            gate = {
                "last_update_success": gate_coordinator.last_update_success,
                "polled_states": len(gate_coordinator.data or {}),
            }

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data({k: v for k, v in entry.data.items() if k != "interface"}, TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "interface": async_redact_data(interface, TO_REDACT),
        "skipped_widgets": _skipped_widgets(interface),
        "clus": clus,
        "gate": gate,
        "devices": devices,
    }
