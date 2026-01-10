from __future__ import annotations
from typing import Literal

from .base import GrentonWidgetDto
from ..components.roller_shutter import GrentonComponentRollerShutterDto

class GrentonWidgetRollerShutterDto(GrentonWidgetDto):
    type: Literal["ROLLER_SHUTTER"] = "ROLLER_SHUTTER"
    components: list[GrentonComponentRollerShutterDto]
