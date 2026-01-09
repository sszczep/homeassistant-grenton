from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceOnOffDouble(BaseGrentonDevice):
    """Device for OnOff Double widgets."""