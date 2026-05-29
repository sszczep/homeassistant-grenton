from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceScene(BaseGrentonDevice):
    """Device for SCENE widgets."""
