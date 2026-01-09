from __future__ import annotations
from pydantic import BaseModel

class GrentonPushNotificationDto(BaseModel):
    cluId: int
    objectId: str
    objectType: str
