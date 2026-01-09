from __future__ import annotations
from pydantic import BaseModel

from ...domain.enums import GrentonUnit

class GrentonComponentDto(BaseModel):
    label: str
    rowId: int
    unit: GrentonUnit
    