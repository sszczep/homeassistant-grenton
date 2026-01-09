from __future__ import annotations
from typing import List
from pydantic import BaseModel

from .encryption import GrentonEncryptionDto
from .clu import GrentonCluDto
from .page import GrentonPageDto
from .push_notification import GrentonPushNotificationDto

from ..domain.enums import GrentonTheme

class GrentonMobileInterfaceDto(BaseModel):
    id: str
    version: int
    name: str
    icon: str
    theme: GrentonTheme
    encryption: GrentonEncryptionDto
    clus: List[GrentonCluDto]
    pages: List[GrentonPageDto]
    pushNotifications: List[GrentonPushNotificationDto]
