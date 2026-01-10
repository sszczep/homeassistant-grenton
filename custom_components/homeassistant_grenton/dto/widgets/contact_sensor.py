from __future__ import annotations
from typing import Literal

from .base import GrentonWidgetDto
from ..objects.contact_sensor import GrentonObjectContactSensorDto

class GrentonWidgetContactSensorDto(GrentonWidgetDto):
    type: Literal["CONTACT_SENSOR"] = "CONTACT_SENSOR"
    label: str
    icon: str
    onIndication: str
    offIndication: str
    reverseState: bool
    object: GrentonObjectContactSensorDto