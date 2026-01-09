from __future__ import annotations
from typing import Literal, List

from .base import GrentonWidgetDto
from ..components.button_bistable import GrentonComponentButtonBistableDto

class GrentonWidgetOnOffDto(GrentonWidgetDto):
    type: Literal["ON_OFF"] = "ON_OFF"
    components: List[GrentonComponentButtonBistableDto]