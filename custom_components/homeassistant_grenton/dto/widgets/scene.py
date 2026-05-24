from __future__ import annotations
from typing import Literal, List

from .base import GrentonWidgetDto
from ..components.button_monostable import GrentonComponentButtonMonostableDto


class GrentonWidgetSceneDto(GrentonWidgetDto):
    type: Literal["SCENE"] = "SCENE"
    components: List[GrentonComponentButtonMonostableDto]
