from __future__ import annotations
from typing import Literal

from .base import GrentonWidgetDto
from ..components.value_double import GrentonComponentValueDoubleDto

class GrentonWidgetValueDoubleDto(GrentonWidgetDto):
    type: Literal["VALUE_DOUBLE"] = "VALUE_DOUBLE"
    componentLeft: GrentonComponentValueDoubleDto
    componentRight: GrentonComponentValueDoubleDto