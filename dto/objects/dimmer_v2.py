from __future__ import annotations
from pydantic import BaseModel

from ..value import GrentonValueUnionDto
from ..action import GrentonActionUnionDto

class GrentonObjectDimmerV2Dto(BaseModel):
    value: GrentonValueUnionDto
    setValueAction: GrentonActionUnionDto
    onAction: GrentonActionUnionDto
    offAction: GrentonActionUnionDto