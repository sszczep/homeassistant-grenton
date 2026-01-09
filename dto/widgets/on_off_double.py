from __future__ import annotations
from typing import Literal, List

from .base import GrentonWidgetDto
from ..components.button_bistable_v2 import GrentonComponentButtonBistableV2Dto

class GrentonWidgetOnOffDoubleDto(GrentonWidgetDto):
    type: Literal["ON_OFF_DOUBLE"] = "ON_OFF_DOUBLE"
    components: List[GrentonComponentButtonBistableV2Dto]