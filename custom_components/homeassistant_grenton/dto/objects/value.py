from __future__ import annotations
from pydantic import BaseModel

from ..value import GrentonValueUnionDto

class GrentonObjectValueDto(BaseModel):
    value: GrentonValueUnionDto
