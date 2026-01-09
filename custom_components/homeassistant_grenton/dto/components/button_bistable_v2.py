from __future__ import annotations
from typing import Literal, List

from .base import GrentonComponentDto
from ..value import GrentonValueUnionDto
from ..action import GrentonActionUnionDto

class GrentonComponentButtonBistableV2Dto(GrentonComponentDto):
    type: Literal["BUTTON_BISTABLE_V2"] = "BUTTON_BISTABLE_V2"
    state: GrentonValueUnionDto
    actions: List[GrentonActionUnionDto]
    onIndication: str
    offIndication: str
