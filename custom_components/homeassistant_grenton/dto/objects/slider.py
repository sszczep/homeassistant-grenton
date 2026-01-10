from __future__ import annotations
from typing import Optional
from pydantic import BaseModel

from ..value import GrentonValueUnionDto
from ..action import GrentonActionUnionDto

class GrentonObjectSliderDto(BaseModel):
    value: GrentonValueUnionDto
    setValueAction: GrentonActionUnionDto
    clickAction: Optional[GrentonActionUnionDto] = None
