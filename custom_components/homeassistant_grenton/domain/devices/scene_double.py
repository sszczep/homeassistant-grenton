from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceSceneDouble(BaseGrentonDevice):
    """Device for SCENE_DOUBLE widgets."""
