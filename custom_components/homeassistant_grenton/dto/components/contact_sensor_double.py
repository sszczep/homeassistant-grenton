from __future__ import annotations
from pydantic import BaseModel

from ..objects.contact_sensor import GrentonObjectContactSensorDto

class GrentonComponentContactSensorDoubleDto(BaseModel):
    label: str
    icon: str
    onIndication: str
    offIndication: str
    reverseState: bool
    object: GrentonObjectContactSensorDto
