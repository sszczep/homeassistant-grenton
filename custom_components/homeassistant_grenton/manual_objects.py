"""Manually added Grenton objects (not present in the myGrenton interface).

Definitions live in config entry options under CONF_MANUAL_OBJECTS:

    {
        "id": "3f2a...",                 # stable, generated
        "kind": "switch",                # see KINDS
        "name": "Pompa cyrkulacyjna",
        "grenton_id": "CLU221001234->DOU5678",
        "transport": "udp" | "gate",
        "area": "Kotłownia",             # optional
        "index": "0",                    # sensor / binary_sensor feature index
        "variable": false,               # sensor: read getVar("<object>") instead
        "reversed": false,               # binary_sensor
        "tilt": false,                   # cover (not for Z-Wave)
        "channel": "w",                  # led_channel: r / g / b / w
    }

Z-Wave objects (ZWA...) are detected by name and use their own indexes.

Each definition becomes one device with one entity. Entities are the same
classes used for interface widgets; only the coordinator (UDP or Gate)
differs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .domain.action import (
    GrentonActionAttributeNumeric,
    GrentonActionMethodNumeric,
    GrentonActionScript,
)
from .domain.clu import GrentonClu
from .domain.devices.base import BaseGrentonDevice
from .domain.entities.base import BaseGrentonEntity
from .domain.entities.binary_sensor import GrentonEntityBinarySensor
from .domain.entities.bistable_switch import GrentonEntityBistableSwitch
from .domain.entities.dimmer import GrentonEntityDimmer
from .domain.entities.led_hex import GrentonEntityLedHex
from .domain.entities.onoff_light import GrentonEntityOnOffLight
from .domain.entities.roller_shutter_v3 import GrentonEntityRollerShutterV3
from .domain.entities.scene_button import GrentonEntitySceneButton
from .domain.entities.thermostat import GrentonEntityThermostat
from .domain.entities.value import GrentonEntityValue
from .domain.enums import GrentonActionEventType, GrentonUnit
from .domain.state_object import (
    GrentonAttributeValueObject,
    GrentonStateObject,
    GrentonVariableValueObject,
)

CONF_MANUAL_OBJECTS = "manual_objects"

TRANSPORT_UDP = "udp"
TRANSPORT_GATE = "gate"
TRANSPORTS = [TRANSPORT_UDP, TRANSPORT_GATE]

KIND_SWITCH = "switch"            # DOUT and similar: get(0), set(0, 1/0)
KIND_LIGHT = "light"              # DOUT driving a lamp
KIND_DIMMER = "dimmer"            # DIMMER: get(0) 0..1, set(0, x); Z-Wave: 0..255, execute(0, x)
KIND_LED_RGB = "led_rgb"          # LED RGB: brightness + colour
KIND_LED_RGBW = "led_rgbw"        # LED RGBW: as RGB + white channel
KIND_LED_CHANNEL = "led_channel"  # single R/G/B/W channel as a dimmable light
KIND_COVER = "cover"              # ROLLER_SHUTTER
KIND_CLIMATE = "climate"          # THERMOSTAT virtual object
KIND_SENSOR = "sensor"            # any feature or user variable
KIND_BINARY_SENSOR = "binary_sensor"
KIND_BUTTON = "button"            # CLU script
KINDS = [
    KIND_SWITCH, KIND_LIGHT, KIND_DIMMER, KIND_LED_RGB, KIND_LED_RGBW, KIND_LED_CHANNEL, KIND_COVER,
    KIND_CLIMATE, KIND_SENSOR, KIND_BINARY_SENSOR, KIND_BUTTON,
]

LED_CHANNELS = ["r", "g", "b", "w"]
# channel -> (set method index, read feature index); values 0..255
_LED_CHANNEL_INDEX = {"r": (3, 3), "g": (4, 4), "b": (5, 5), "w": (12, 15)}

_GRENTON_ID = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*->\s*([A-Za-z_][A-Za-z0-9_]*)\s*$")


class InvalidGrentonId(ValueError):
    pass


def is_zwave(object_name: str) -> bool:
    """Z-Wave objects (ZWA...) use different feature/method indexes."""
    return object_name.upper().startswith("ZWA")


def parse_grenton_id(value: str) -> tuple[str, str]:
    """'CLU221001234->DOU5678' -> ('CLU221001234', 'DOU5678')."""
    match = _GRENTON_ID.match(value or "")
    if not match:
        raise InvalidGrentonId(value)
    return match.group(1), match.group(2)


def find_interface_clu(clu_name: str, clus: list[GrentonClu]) -> GrentonClu | None:
    """Match the CLU part of a Grenton id against CLUs from the interface."""
    wanted = clu_name.lower()
    for clu in clus:
        candidates = {clu.id, clu.name, f"CLU{clu.serial_number}"}
        if wanted in {c.lower() for c in candidates if c}:
            return clu
    return None


@dataclass
class GrentonDeviceManual(BaseGrentonDevice):
    """Device created from a manual object definition."""


def _attr(clu: str, obj: str, index: str | int) -> GrentonAttributeValueObject:
    return GrentonAttributeValueObject(clu_id=clu, object_name=obj, index=str(index))


def _set(clu: str, obj: str, index: int, value: str, event: GrentonActionEventType = GrentonActionEventType.CLICK):
    return GrentonActionAttributeNumeric(clu, obj, event, value, index=str(index))


def _exec(clu: str, obj: str, index: int, value: str = "0", event: GrentonActionEventType = GrentonActionEventType.CLICK):
    return GrentonActionMethodNumeric(clu, obj, event, value, index=str(index))


def build_entity(definition: dict[str, Any], coordinator: Any, clu_id: str, object_name: str) -> BaseGrentonEntity:
    kind = definition["kind"]
    uid = f"manual_{definition['id']}"
    label = definition["name"]
    on, off = GrentonActionEventType.ON, GrentonActionEventType.OFF

    if kind == KIND_SWITCH:
        return GrentonEntityBistableSwitch(
            coordinator=coordinator, id=uid, label=label, unit=GrentonUnit.UNKNOWN,
            state_object=_attr(clu_id, object_name, 0),
            action_on=_set(clu_id, object_name, 0, "1", on),
            action_off=_set(clu_id, object_name, 0, "0", off),
        )
    if kind == KIND_LIGHT:
        return GrentonEntityOnOffLight(
            coordinator=coordinator, id=uid, label=label,
            state_object=_attr(clu_id, object_name, 0),
            action_on=_set(clu_id, object_name, 0, "1", on),
            action_off=_set(clu_id, object_name, 0, "0", off),
        )
    zwave = is_zwave(object_name)
    if kind == KIND_DIMMER:
        if zwave:
            return GrentonEntityDimmer(
                coordinator=coordinator, id=uid, label=label, min=0, max=255, precision=0,
                state_object=_attr(clu_id, object_name, 0),
                action_on=_exec(clu_id, object_name, 0, "255", on),
                action_off=_exec(clu_id, object_name, 0, "0", off),
                action_set_value=_exec(clu_id, object_name, 0, "$value$"),
            )
        return GrentonEntityDimmer(
            coordinator=coordinator, id=uid, label=label, min=0, max=1, precision=2,
            state_object=_attr(clu_id, object_name, 0),
            action_on=_set(clu_id, object_name, 0, "1", on),
            action_off=_set(clu_id, object_name, 0, "0", off),
            action_set_value=_set(clu_id, object_name, 0, "$value$"),
        )
    if kind in (KIND_LED_RGB, KIND_LED_RGBW):
        return GrentonEntityLedHex(
            coordinator=coordinator, id=uid, label=label, clu_id=clu_id, object_name=object_name,
            white=kind == KIND_LED_RGBW, zwave=zwave,
        )
    if kind == KIND_LED_CHANNEL:
        channel = str(definition.get("channel") or "w").lower()
        set_index, read_index = _LED_CHANNEL_INDEX[channel]
        return GrentonEntityDimmer(
            coordinator=coordinator, id=uid, label=label, min=0, max=255, precision=0,
            state_object=_attr(clu_id, object_name, read_index),
            action_on=_exec(clu_id, object_name, set_index, "255", on),
            action_off=_exec(clu_id, object_name, set_index, "0", off),
            action_set_value=_exec(clu_id, object_name, set_index, "$value$"),
        )
    if kind == KIND_COVER:
        if zwave:
            # Z-Wave roller shutter: state get(2), position get(4), set execute(7, p); no tilt
            return GrentonEntityRollerShutterV3(
                coordinator=coordinator, id=uid, label=label,
                cover_state=_attr(clu_id, object_name, 2),
                cover_position=_attr(clu_id, object_name, 4),
                set_position=_exec(clu_id, object_name, 7),
                stop=_exec(clu_id, object_name, 3),
            )
        return GrentonEntityRollerShutterV3(
            coordinator=coordinator, id=uid, label=label,
            cover_state=_attr(clu_id, object_name, 0),
            cover_position=_attr(clu_id, object_name, 7),
            set_position=_exec(clu_id, object_name, 10),
            cover_tilt_position=_attr(clu_id, object_name, 8) if definition.get("tilt") else None,
            set_tilt_position=_exec(clu_id, object_name, 9) if definition.get("tilt") else None,
            stop=_exec(clu_id, object_name, 3),
        )
    if kind == KIND_CLIMATE:
        return GrentonEntityThermostat(
            coordinator=coordinator, id=uid, label=label, clu_id=clu_id, object_name=object_name,
        )
    if kind in (KIND_SENSOR, KIND_BINARY_SENSOR):
        state: GrentonStateObject
        if definition.get("variable"):
            state = GrentonVariableValueObject(clu_id=clu_id, object_name=object_name, index=object_name)
        else:
            state = _attr(clu_id, object_name, definition.get("index") or 0)
        if kind == KIND_SENSOR:
            return GrentonEntityValue(coordinator=coordinator, id=uid, label=label, state_object=state)
        return GrentonEntityBinarySensor(
            coordinator=coordinator, id=uid, label=label,
            reversed=bool(definition.get("reversed")), state_object=state,
        )
    if kind == KIND_BUTTON:
        return GrentonEntitySceneButton(
            coordinator=coordinator, id=uid, label=label,
            script_action=GrentonActionScript(clu_id, object_name, GrentonActionEventType.CLICK, ""),
        )
    raise ValueError(f"Unknown manual object kind: {kind}")


def build_manual_devices(
    definitions: list[dict[str, Any]],
    clus: list[GrentonClu],
    udp_coordinator: Any,
    gate_coordinator: Any | None,
    logger: Any,
) -> list[BaseGrentonDevice]:
    devices: list[BaseGrentonDevice] = []
    for definition in definitions:
        try:
            clu_name, object_name = parse_grenton_id(definition["grenton_id"])
            if definition.get("transport") == TRANSPORT_GATE:
                if gate_coordinator is None:
                    logger.warning("Skipping %s: Gate HTTP is not configured", definition["name"])
                    continue
                coordinator, clu_id = gate_coordinator, clu_name
            else:
                clu = find_interface_clu(clu_name, clus)
                if clu is None:
                    logger.warning("Skipping %s: CLU %s is not in the interface (use Gate HTTP)", definition["name"], clu_name)
                    continue
                coordinator, clu_id = udp_coordinator, clu.id

            entity = build_entity(definition, coordinator, clu_id, object_name)
        except (KeyError, ValueError) as err:
            logger.error("Invalid manual object %s: %s", definition, err)
            continue

        device = GrentonDeviceManual(
            type=f"MANUAL_{definition['kind'].upper()}",
            id=f"manual_{definition['id']}",
            entities=[entity],
        )
        device.apply_naming(definition["name"], (definition.get("area") or "").strip() or None)
        devices.append(device)
    return devices
