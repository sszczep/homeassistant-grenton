"""Import objects from the "Grenton Objects" integration (domain grenton_objects).

Every Grenton Objects config entry describes one object (CLU->OBJECT plus a
type). Each becomes a manual object of this integration; the new entity takes
over the old entity_id, user name, icon and area, so automations, scripts and
dashboards keep working. Old entries are removed so their entity_ids are free.

Only the entry data is read (no code of that integration is used). Types are
mapped to the same Home Assistant platform, otherwise the entity_id would change.
"""
from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from homeassistant.const import CONF_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .domain.clu import GrentonClu
from .manual_objects import (
    KIND_BINARY_SENSOR,
    KIND_BUTTON,
    KIND_CLIMATE,
    KIND_COVER,
    KIND_DIMMER,
    KIND_LED_CHANNEL,
    KIND_LED_RGB,
    KIND_LED_RGBW,
    KIND_LIGHT,
    KIND_SENSOR,
    KIND_SWITCH,
    TRANSPORT_GATE,
    TRANSPORT_UDP,
    find_interface_clu,
)

SOURCE_DOMAIN = "grenton_objects"

# Grenton Objects sensor types -> feature index read with get(<index>)
_SENSOR_INDEX = {
    "MODBUS": 14,
    "MODBUS_VALUE": 20,
    "MODBUS_RTU": 22,
    "MODBUS_CLIENT": 19,
    "MODBUS_SERVER": 10,
    "MODBUS_SLAVE_RTU": 10,
    "RELAY_POWER": 5,
    "ANALOG_SCALED_VALUE_OR_VALUE_%": 1,
}
_LIGHT_KIND = {
    "DOUT": (KIND_LIGHT, None),
    "DIMMER": (KIND_DIMMER, None),
    "RGB": (KIND_LED_RGB, None),
    "RGB+W": (KIND_LED_RGBW, None),
    "LED_R": (KIND_LED_CHANNEL, "r"),
    "LED_G": (KIND_LED_CHANNEL, "g"),
    "LED_B": (KIND_LED_CHANNEL, "b"),
    "LED_W": (KIND_LED_CHANNEL, "w"),
}
_OBJECT_NAME = re.compile(r"^[A-Z]{3}\d{4}$")


@dataclass
class ImportCandidate:
    source_entry_id: str
    title: str
    grenton_id: str
    platform: str | None              # HA domain of the old entity
    old_entity_id: str | None
    definition: dict[str, Any] | None  # None = cannot be imported
    reason: str | None = None          # why not
    entity_config: dict[str, Any] = field(default_factory=dict)
    api_endpoint: str | None = None


def _definition(data: dict[str, Any], platform: str | None) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
    grenton_id = str(data.get("grenton_id") or "").strip()
    grenton_type = str(data.get("grenton_type") or "")
    name = str(data.get("name") or grenton_id)
    if "->" not in grenton_id:
        return None, {}, "no_clu"  # variable on the Gate itself: no CLU to address
    clu, obj = (part.strip() for part in grenton_id.split("->", 1))
    base: dict[str, Any] = {"id": uuid.uuid4().hex[:12], "name": name, "grenton_id": f"{clu}->{obj}", "area": ""}
    config: dict[str, Any] = {}

    if platform == "switch":
        return {**base, "kind": KIND_SWITCH}, config, None
    if platform == "light":
        kind, channel = _LIGHT_KIND.get(grenton_type, (KIND_LIGHT, None))
        definition = {**base, "kind": kind}
        if channel:
            definition["channel"] = channel
        return definition, config, None
    if platform == "cover":
        return {**base, "kind": KIND_COVER, "tilt": False}, config, None
    if platform == "climate":
        return {**base, "kind": KIND_CLIMATE}, config, None
    if platform == "button":
        return {**base, "kind": KIND_BUTTON}, config, None
    if platform == "binary_sensor":
        if data.get("device_class"):
            config["device_class"] = data["device_class"]
        return {**base, "kind": KIND_BINARY_SENSOR, "index": "0", "variable": False,
                "reversed": bool(data.get("reversed"))}, config, None
    if platform == "sensor":
        definition = {**base, "kind": KIND_SENSOR}
        if _OBJECT_NAME.match(obj):
            definition.update(index=str(_SENSOR_INDEX.get(grenton_type, 0)), variable=False)
        else:
            definition.update(index="0", variable=True)  # CLU->userFeature
        for key in ("device_class", "state_class", CONF_UNIT_OF_MEASUREMENT):
            if data.get(key):
                config[key] = data[key]
        return definition, config, None
    return None, {}, "unknown_type"


def find_candidates(hass: HomeAssistant) -> list[ImportCandidate]:
    registry = er.async_get(hass)
    candidates: list[ImportCandidate] = []
    for entry in hass.config_entries.async_entries(SOURCE_DOMAIN):
        data = {**entry.data, **entry.options}
        entities = er.async_entries_for_config_entry(registry, entry.entry_id)
        old = entities[0] if entities else None
        platform = old.domain if old else None
        definition, config, reason = _definition(data, platform)
        if platform is None and reason is None:
            reason = "no_entity"
            definition = None
        candidates.append(ImportCandidate(
            source_entry_id=entry.entry_id,
            title=entry.title,
            grenton_id=str(data.get("grenton_id") or ""),
            platform=platform,
            old_entity_id=old.entity_id if old else None,
            definition=definition,
            reason=reason,
            entity_config=config,
            api_endpoint=data.get("api_endpoint"),
        ))
    return candidates


def most_common_endpoint(candidates: list[ImportCandidate]) -> str | None:
    endpoints = Counter(c.api_endpoint for c in candidates if c.api_endpoint)
    if not endpoints:
        return None
    url = endpoints.most_common(1)[0][0]
    return url if str(url).startswith(("http://", "https://")) else f"http://{url}"


async def async_import(
    hass: HomeAssistant,
    target_entry: Any,
    candidates: list[ImportCandidate],
    clus: list[GrentonClu],
    prefer_udp: bool,
    take_over: bool,
) -> list[dict[str, Any]]:
    """Remove the old entries (if take_over) and pre-register the new entities.

    Returns the manual object definitions to add; the caller stores them in the
    options (which reloads the entry and creates the entities).
    """
    registry = er.async_get(hass)
    definitions: list[dict[str, Any]] = []
    takeovers: list[tuple[str, str, er.RegistryEntry | None]] = []

    for candidate in candidates:
        if candidate.definition is None:
            continue
        definition = dict(candidate.definition)
        clu_name = definition["grenton_id"].split("->", 1)[0]
        use_udp = prefer_udp and find_interface_clu(clu_name, clus) is not None
        definition["transport"] = TRANSPORT_UDP if use_udp else TRANSPORT_GATE
        definitions.append(definition)
        old = registry.async_get(candidate.old_entity_id) if candidate.old_entity_id else None
        takeovers.append((candidate.platform or "", f"manual_{definition['id']}", old))

    if take_over:
        for candidate in candidates:
            if candidate.definition is not None:
                await hass.config_entries.async_remove(candidate.source_entry_id)

        for platform, unique_id, old in takeovers:
            if old is None:
                continue
            object_id = old.entity_id.split(".", 1)[1]
            new = registry.async_get_or_create(
                platform, "grenton", unique_id,
                suggested_object_id=object_id,
                config_entry=target_entry,
            )
            if new.entity_id != old.entity_id and registry.async_get(old.entity_id) is None:
                new = registry.async_update_entity(new.entity_id, new_entity_id=old.entity_id)
            registry.async_update_entity(
                new.entity_id,
                name=old.name,
                icon=old.icon,
                area_id=old.area_id,
                aliases=set(old.aliases),
                labels=set(old.labels),
            )
    return definitions


def entity_configs(candidates: list[ImportCandidate], definitions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Sensor/binary sensor class and unit for options['entities'], by new unique id."""
    by_name = {d["grenton_id"] + "|" + d["name"]: d for d in definitions}
    result: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if candidate.definition is None or not candidate.entity_config:
            continue
        definition = by_name.get(candidate.definition["grenton_id"] + "|" + candidate.definition["name"])
        if definition is not None:
            result[f"manual_{definition['id']}"] = dict(candidate.entity_config)
    return result
