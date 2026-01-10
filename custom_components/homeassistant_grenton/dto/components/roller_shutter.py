from __future__ import annotations
from typing import Literal, List

from .base import GrentonComponentDto
from ..value import GrentonValueUnionDto
from ..action import GrentonActionUnionDto

from ...domain.enums import GrentonComponentIndication

class GrentonComponentRollerShutterDto(GrentonComponentDto):
    type: Literal["BUTTON_BISTABLE"] = "BUTTON_BISTABLE"
    image: str
    state: GrentonValueUnionDto
    indication: GrentonComponentIndication
    actions: List[GrentonActionUnionDto]

