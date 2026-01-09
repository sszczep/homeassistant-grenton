from __future__ import annotations
from pydantic import BaseModel

class GrentonEncryptionDto(BaseModel):
    key: str
    iv: str
