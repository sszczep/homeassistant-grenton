from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceRollerShutterV3(BaseGrentonDevice):
    """Device for Roller Shutter V3 widgets."""