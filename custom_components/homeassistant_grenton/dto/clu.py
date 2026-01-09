from __future__ import annotations
from pydantic import BaseModel

from ..domain.enums import GrentonCluConnectionType

class GrentonCluDto(BaseModel):
    id: str
    serialNumber: str
    name: str
    ip: str
    port: int
    connectionType: GrentonCluConnectionType
