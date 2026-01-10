from __future__ import annotations
from typing import Literal

from .base import GrentonWidgetDto
from ..objects.slider import GrentonObjectSliderDto

from ...domain.enums import GrentonUnit

class GrentonWidgetSliderDto(GrentonWidgetDto):
    type: Literal["SLIDER"] = "SLIDER"
    label: str
    icon: str
    unit: GrentonUnit
    min: float
    max: float
    precision: int
    object: GrentonObjectSliderDto
