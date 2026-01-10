from __future__ import annotations
from typing import Literal

from .base import GrentonComponentDto

class GrentonComponentCameraStreamDto(GrentonComponentDto):
    type: Literal["CAMERA_STREAM"] = "CAMERA_STREAM"
    image: str
    value: str
