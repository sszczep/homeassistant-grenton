from __future__ import annotations
from typing import Literal, List

from .base import GrentonWidgetDto
from ..components.camera import GrentonComponentCameraStreamDto

class GrentonWidgetCameraDto(GrentonWidgetDto):
    type: Literal["CAMERA"] = "CAMERA"
    components: List[GrentonComponentCameraStreamDto]