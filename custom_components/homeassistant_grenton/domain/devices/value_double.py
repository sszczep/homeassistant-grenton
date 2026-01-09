from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceValueDouble(BaseGrentonDevice):
    """Device for Value Double widgets."""