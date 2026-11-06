"""Per-page form for device names, entity friendly names, units and precision.

Used by the import flow (config + reconfigure) and by the options menu
("Names, units and precision"). Each interface page is one form: the area of
the page, then one section per widget with

    single-entity widget:  name, [device class, unit, precision]
    multi-entity widget:   device name, then per entity: friendly name,
                           [device class, unit, precision]

Where things are stored:
    entry.data[device_names][widget_id]            custom device name
    entry.data[page_areas][page_name]              suggested area ("" = none)
    entry.options[entity_overrides][uid]           {"name": str, "precision": int}
    entry.options[entities][uid]                   device_class / unit_of_measurement
                                                   (merged into the entity's own config)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import voluptuous as vol

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.sensor.const import DEVICE_CLASS_UNITS
from homeassistant.const import CONF_UNIT_OF_MEASUREMENT
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .domain.clu import GrentonClu
from .domain.entities.base import CONF_ENTITY_OVERRIDES
from .domain.entities.binary_sensor import GrentonEntityBinarySensor
from .domain.entities.value import GrentonEntityValue
from .dto.mobile_interface import GrentonMobileInterfaceDto
from .mappers.device_mapper import DeviceMapper
from .naming import CONF_DEVICE_NAMES, CONF_PAGE_AREAS, resolve_page_area

_LOGGER = logging.getLogger(__name__)

CONF_AREA = "area"
CONF_ENTITIES = "entities"

KIND_SENSOR = "sensor"          # configurable class + unit + precision
KIND_SENSOR_FIXED = "sensor_fixed"  # precision only (e.g. multisensor)
KIND_BINARY = "binary"          # configurable class
KIND_OTHER = "other"            # name only

_LABELS = {
    "pl": {
        "device": "Nazwa urządzenia",
        "name": "Nazwa",
        "entity_name": "nazwa",
        "device_class": "klasa urządzenia",
        "unit": "jednostka",
        "precision": "dokładność (miejsca po przecinku)",
    },
    "en": {
        "device": "Device name",
        "name": "Name",
        "entity_name": "name",
        "device_class": "device class",
        "unit": "unit",
        "precision": "precision (decimals)",
    },
}

_ALL_UNITS = sorted(
    {
        str(getattr(unit, "value", unit))
        for units in DEVICE_CLASS_UNITS.values()
        for unit in units
        if unit is not None
    }
    | {"%", "°C", "ppm", "lx", "W", "kWh", "V", "A", "Pa", "hPa", "dB"}
)


class _PreviewCoordinator:
    """Just enough of a coordinator to map widgets without connecting."""

    last_update_success = True

    def __init__(self, hass: Any, clus: list[GrentonClu], options: dict[str, Any]) -> None:
        self.hass = hass
        self.clus = clus
        self.config_entry = SimpleNamespace(options=options, data={}, entry_id="preview", title="preview")

    def register_component_state(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_value_for_component(self, *args: Any, **kwargs: Any) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


@dataclass
class EntityModel:
    uid: str
    label: str
    key: str                      # unique, readable discriminator inside its device
    kind: str
    default_friendly: str         # with the label-based device name
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceModel:
    widget_id: str
    widget_type: str
    default_name: str
    entities: list[EntityModel]


@dataclass
class PageModel:
    name: str
    devices: list[DeviceModel]


def _kind(entity: Any) -> str:
    if isinstance(entity, GrentonEntityValue):
        return KIND_SENSOR
    if isinstance(entity, SensorEntity):
        return KIND_SENSOR_FIXED
    if isinstance(entity, GrentonEntityBinarySensor):
        return KIND_BINARY
    return KIND_OTHER


def build_pages(hass: Any, interface: dict[str, Any], options: dict[str, Any]) -> list[PageModel]:
    """Map the interface with a preview coordinator, grouped by page."""
    dto = GrentonMobileInterfaceDto(**interface)
    coordinator = _PreviewCoordinator(hass, [GrentonClu.from_dto(clu) for clu in dto.clus], options)
    pages: list[PageModel] = []
    for page in dto.pages:
        devices: list[DeviceModel] = []
        for widget in page.widgets:
            try:
                device = DeviceMapper.to_domain(widget, coordinator)  # type: ignore[arg-type]
            except Exception as err:  # noqa: BLE001 - a broken widget must not break the form
                _LOGGER.debug("Preview of widget %s failed: %s", widget.id, err)
                continue
            if not device.entities:
                continue
            labels = [e.label.strip() for e in device.entities]
            entities: list[EntityModel] = []
            for entity in device.entities:
                uid = entity.unique_id or ""
                label = entity.label.strip() or uid
                key = label
                if labels.count(entity.label.strip()) > 1 or not entity.label.strip():
                    key = f"{label} [{uid.removeprefix(widget.id).lstrip('_') or uid}]"
                single = len(device.entities) == 1
                entities.append(EntityModel(
                    uid=uid,
                    label=label,
                    key=key,
                    kind=_kind(entity),
                    default_friendly=device.default_name if single else f"{device.default_name} {label}",
                    config=dict(getattr(entity, "_config", {}) or {}),
                ))
            devices.append(DeviceModel(widget.id, widget.type, device.default_name, entities))
        if devices:
            pages.append(PageModel(page.name, devices))
    return pages


def _labels(language: str | None) -> dict[str, str]:
    return _LABELS["pl" if (language or "").lower().startswith("pl") else "en"]


def _suggested(value: Any) -> dict[str, Any]:
    return {"suggested_value": value} if value not in (None, "") else {}


def _measurement_fields(entity: EntityModel, prefix: str, l: dict[str, str],
                        overrides: dict[str, Any], schema: dict[Any, Any]) -> None:
    current = overrides.get(entity.uid, {})
    if entity.kind == KIND_SENSOR:
        schema[vol.Optional(f"{prefix}{l['device_class']}", description=_suggested(entity.config.get("device_class")))] = (
            selector.SelectSelector(selector.SelectSelectorConfig(
                options=[dc.value for dc in SensorDeviceClass],
                translation_key="sensor_device_classes",
                mode=selector.SelectSelectorMode.DROPDOWN, sort=True,
            ))
        )
        schema[vol.Optional(f"{prefix}{l['unit']}", description=_suggested(entity.config.get(CONF_UNIT_OF_MEASUREMENT)))] = (
            selector.SelectSelector(selector.SelectSelectorConfig(
                options=_ALL_UNITS, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN,
            ))
        )
    if entity.kind == KIND_BINARY:
        schema[vol.Optional(f"{prefix}{l['device_class']}", description=_suggested(entity.config.get("device_class")))] = (
            selector.SelectSelector(selector.SelectSelectorConfig(
                options=[dc.value for dc in BinarySensorDeviceClass],
                translation_key="binary_sensor_device_classes",
                mode=selector.SelectSelectorMode.DROPDOWN, sort=True,
            ))
        )
    if entity.kind in (KIND_SENSOR, KIND_SENSOR_FIXED):
        schema[vol.Optional(f"{prefix}{l['precision']}", description=_suggested(current.get("precision")))] = (
            selector.NumberSelector(selector.NumberSelectorConfig(min=0, max=6, step=1, mode=selector.NumberSelectorMode.BOX))
        )


def section_key(device: DeviceModel) -> str:
    return f"{device.default_name} ({device.widget_type}, {device.widget_id})"


def page_schema(page: PageModel, data: dict[str, Any], options: dict[str, Any], language: str | None) -> vol.Schema:
    l = _labels(language)
    names: dict[str, str] = data.get(CONF_DEVICE_NAMES) or {}
    overrides: dict[str, Any] = options.get(CONF_ENTITY_OVERRIDES) or {}
    schema: dict[Any, Any] = {
        vol.Optional(CONF_AREA, default=resolve_page_area(page.name, data.get(CONF_PAGE_AREAS)) or ""): str,
    }
    for device in page.devices:
        fields: dict[Any, Any] = {}
        device_name = names.get(device.widget_id) or device.default_name
        if len(device.entities) == 1:
            fields[vol.Optional(l["name"], default=device_name)] = str
            _measurement_fields(device.entities[0], "", l, overrides, fields)
        else:
            fields[vol.Optional(l["device"], default=device_name)] = str
            for entity in device.entities:
                friendly = (overrides.get(entity.uid) or {}).get("name") or f"{device_name} {entity.label}"
                fields[vol.Optional(f"{entity.key}: {l['entity_name']}", default=friendly)] = str
                _measurement_fields(entity, f"{entity.key}: ", l, overrides, fields)
        schema[vol.Optional(section_key(device))] = section(vol.Schema(fields), {"collapsed": len(page.devices) > 6})
    return vol.Schema(schema)


def _set(target: dict[str, Any], uid: str, key: str, value: Any) -> None:
    entry = dict(target.get(uid) or {})
    if value in (None, ""):
        entry.pop(key, None)
    else:
        entry[key] = value
    if entry:
        target[uid] = entry
    else:
        target.pop(uid, None)


def apply_page_input(page: PageModel, user_input: dict[str, Any], data: dict[str, Any],
                     options: dict[str, Any], language: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (data, options) updated from one submitted page form."""
    l = _labels(language)
    data = dict(data)
    options = dict(options)
    names = dict(data.get(CONF_DEVICE_NAMES) or {})
    areas = dict(data.get(CONF_PAGE_AREAS) or {})
    overrides = {k: dict(v) for k, v in (options.get(CONF_ENTITY_OVERRIDES) or {}).items()}
    entities_cfg = {k: dict(v) if isinstance(v, dict) else v for k, v in (options.get(CONF_ENTITIES) or {}).items()}

    areas[page.name] = str(user_input.get(CONF_AREA, "")).strip()

    for device in page.devices:
        values: dict[str, Any] = user_input.get(section_key(device)) or {}
        single = len(device.entities) == 1
        previous_name = names.get(device.widget_id) or device.default_name
        name = str(values.get(l["name"] if single else l["device"], "")).strip()
        effective_name = name or device.default_name
        if name and name != device.default_name:
            names[device.widget_id] = name
        else:
            names.pop(device.widget_id, None)

        for entity in device.entities:
            prefix = "" if single else f"{entity.key}: "
            if not single:
                friendly = str(values.get(f"{entity.key}: {l['entity_name']}", "")).strip()
                # The default friendly name is "<device name> <label>" (old or new device name)
                defaults = {f"{n} {entity.label}" for n in (previous_name, effective_name, device.default_name)}
                _set(overrides, entity.uid, "name", friendly if friendly and friendly not in defaults else None)

            if entity.kind in (KIND_SENSOR, KIND_SENSOR_FIXED):
                precision = values.get(f"{prefix}{l['precision']}")
                _set(overrides, entity.uid, "precision", int(precision) if precision not in (None, "") else None)

            if entity.kind in (KIND_SENSOR, KIND_BINARY):
                device_class = values.get(f"{prefix}{l['device_class']}") or None
                unit = values.get(f"{prefix}{l['unit']}") if entity.kind == KIND_SENSOR else None
                changed = device_class != entity.config.get("device_class") or (
                    entity.kind == KIND_SENSOR and (unit or None) != entity.config.get(CONF_UNIT_OF_MEASUREMENT)
                )
                if changed:
                    config = dict(entities_cfg.get(entity.uid) or entity.config)
                    config["device_class"] = device_class
                    if entity.kind == KIND_SENSOR:
                        config[CONF_UNIT_OF_MEASUREMENT] = unit or None
                    entities_cfg[entity.uid] = config

    data[CONF_DEVICE_NAMES] = names
    data[CONF_PAGE_AREAS] = areas
    options[CONF_ENTITY_OVERRIDES] = overrides
    options[CONF_ENTITIES] = entities_cfg
    return data, options


def apply_name_overrides(
    hass: Any,
    entry: Any,
    old_overrides: dict[str, Any] | None,
    new_overrides: dict[str, Any] | None,
) -> None:
    """Apply friendly names as entity registry names (like a rename in the HA UI).

    A name the user later sets in HA itself wins: it is only replaced when it
    is empty or still equal to the previously applied override.
    """
    from homeassistant.helpers import entity_registry as er

    old_overrides = old_overrides or {}
    new_overrides = new_overrides or {}
    if not any((v or {}).get("name") for v in (*old_overrides.values(), *new_overrides.values())):
        return
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        uid = reg_entry.unique_id
        old = (old_overrides.get(uid) or {}).get("name")
        new = (new_overrides.get(uid) or {}).get("name")
        if new == old and (new is None or reg_entry.name is not None):
            continue
        if reg_entry.name in (None, old) and reg_entry.name != new:
            registry.async_update_entity(reg_entry.entity_id, name=new)
