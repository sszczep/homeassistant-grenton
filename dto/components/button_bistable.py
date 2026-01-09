from __future__ import annotations
from typing import Literal, List

from .base import GrentonComponentDto
from ..value import GrentonValueUnionDto
from ..action import GrentonActionUnionDto

class GrentonComponentButtonBistableDto(GrentonComponentDto):
    type: Literal["BUTTON_BISTABLE"] = "BUTTON_BISTABLE"
    state: GrentonValueUnionDto
    actions: List[GrentonActionUnionDto]
    onIndication: str
    offIndication: str
