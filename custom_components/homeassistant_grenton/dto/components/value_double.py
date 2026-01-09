from __future__ import annotations
from pydantic import BaseModel

from ..objects.value import GrentonObjectValueDto

from ...domain.enums import GrentonUnit, GrentonValueType

class GrentonComponentValueDoubleDto(BaseModel):
    label: str
    icon: str
    unit: GrentonUnit
    valueType: GrentonValueType
    precision: int
    object: GrentonObjectValueDto
