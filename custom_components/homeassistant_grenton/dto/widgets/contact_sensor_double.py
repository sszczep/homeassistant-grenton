from __future__ import annotations
from typing import Literal

from .base import GrentonWidgetDto
from ..components.contact_sensor_double import GrentonComponentContactSensorDoubleDto

class GrentonWidgetContactSensorDoubleDto(GrentonWidgetDto):
    type: Literal["CONTACT_SENSOR_DOUBLE"] = "CONTACT_SENSOR_DOUBLE"
    componentLeft: GrentonComponentContactSensorDoubleDto
    componentRight: GrentonComponentContactSensorDoubleDto