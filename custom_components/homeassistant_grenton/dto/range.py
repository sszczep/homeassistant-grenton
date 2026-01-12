from __future__ import annotations
from pydantic import BaseModel

class GrentonRange(BaseModel):
    min: int
    max: int
