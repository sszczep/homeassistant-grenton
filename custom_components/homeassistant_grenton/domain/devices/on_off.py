from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceOnOff(BaseGrentonDevice):
    """Device for OnOff widgets."""