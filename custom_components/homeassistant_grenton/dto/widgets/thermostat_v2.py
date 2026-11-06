"""Thermostat widget with optional cooling bindings from the mobile interface."""

from typing import Literal

from ..objects.thermostat_v2 import GrentonObjectThermostatV2Dto
from .base import GrentonWidgetDto


class GrentonWidgetThermostatV2Dto(GrentonWidgetDto):
    type: Literal["THERMOSTAT_V2"] = "THERMOSTAT_V2"
    label: str
    icon: str
    no_of_fan_speeds: int = 0
    object: GrentonObjectThermostatV2Dto
