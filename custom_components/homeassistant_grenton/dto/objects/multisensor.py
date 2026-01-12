from __future__ import annotations
from typing import Optional
from pydantic import BaseModel

from ..value import GrentonValueUnionDto

class GrentonObjectMultisensorDto(BaseModel):
    value: GrentonValueUnionDto
    minValue: Optional[GrentonValueUnionDto] = None
    maxValue: Optional[GrentonValueUnionDto] = None
    threshold: Optional[GrentonValueUnionDto] = None
    sensitivity: Optional[GrentonValueUnionDto] = None