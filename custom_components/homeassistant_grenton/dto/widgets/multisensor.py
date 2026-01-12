from __future__ import annotations
from typing import Literal

from .base import GrentonWidgetDto
from ..objects.multisensor import GrentonObjectMultisensorDto

class GrentonWidgetMultisensorDto(GrentonWidgetDto):
    type: Literal["MULTISENSOR"] = "MULTISENSOR"
    label: str
    icon: str
    labelVisible: bool
    objectAirCo2: GrentonObjectMultisensorDto
    objectSound: GrentonObjectMultisensorDto
    objectAirVoc: GrentonObjectMultisensorDto
    objectLight: GrentonObjectMultisensorDto
    objectPressure: GrentonObjectMultisensorDto
    objectHumidity: GrentonObjectMultisensorDto
    objectTemperature: GrentonObjectMultisensorDto
