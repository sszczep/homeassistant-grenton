from __future__ import annotations
from typing import Literal, List

from .base import GrentonComponentDto
from ..action import GrentonActionUnionDto


class GrentonComponentButtonMonostableDto(GrentonComponentDto):
    type: Literal["BUTTON_MONOSTABLE"] = "BUTTON_MONOSTABLE"
    actions: List[GrentonActionUnionDto]
