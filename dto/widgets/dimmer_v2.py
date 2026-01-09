from __future__ import annotations
from typing import Literal

from .base import GrentonWidgetDto
from ..objects.dimmer_v2 import GrentonObjectDimmerV2Dto

class GrentonWidgetDimmerV2Dto(GrentonWidgetDto):
    type: Literal["DIMMER_V2"] = "DIMMER_V2"
    label: str
    icon: str
    min: float
    max: float
    precision: int
    object: GrentonObjectDimmerV2Dto
