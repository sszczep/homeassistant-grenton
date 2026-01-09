from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceDimmerV2(BaseGrentonDevice):
    """Device for Dimmer V2 widgets."""