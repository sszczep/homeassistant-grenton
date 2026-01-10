from __future__ import annotations
from typing import Literal

from .base import GrentonWidgetDto
from ..objects.roller_shutter_v3 import GrentonObjectRollerShutterV3Dto

class GrentonWidgetRollerShutterV3Dto(GrentonWidgetDto):
    type: Literal["ROLLER_SHUTTER_V3"] = "ROLLER_SHUTTER_V3"
    icon: str
    label: str
    object: GrentonObjectRollerShutterV3Dto
