from __future__ import annotations
from typing import Literal

from .base import GrentonWidgetDto
from ..objects.value import GrentonObjectValueDto

from ...domain.enums import GrentonUnit, GrentonValueType

class GrentonWidgetValueV2Dto(GrentonWidgetDto):
    type: Literal["VALUE_V2"] = "VALUE_V2"
    label: str
    icon: str
    unit: GrentonUnit
    valueType: GrentonValueType
    precision: int
    object: GrentonObjectValueDto
