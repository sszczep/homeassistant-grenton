from __future__ import annotations
from typing import Literal, List

from .base import GrentonWidgetDto
from ..components.led import GrentonComponentLedUnionDto

class GrentonWidgetLedDto(GrentonWidgetDto):
    type: Literal["LED"] = "LED"
    components: List[GrentonComponentLedUnionDto]