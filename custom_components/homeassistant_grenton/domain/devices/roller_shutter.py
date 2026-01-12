from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceRollerShutter(BaseGrentonDevice):
    """Device for Roller Shutter widgets."""