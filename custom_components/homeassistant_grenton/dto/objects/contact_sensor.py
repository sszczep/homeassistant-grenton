from __future__ import annotations
from typing import Optional
from pydantic import BaseModel

from ..value import GrentonValueUnionDto
from ..action import GrentonActionUnionDto

class GrentonObjectContactSensorDto(BaseModel):
    value: GrentonValueUnionDto
    clickAction: Optional[GrentonActionUnionDto] = None