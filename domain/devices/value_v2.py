from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceValueV2(BaseGrentonDevice):
    """Device for Value V2 widgets."""