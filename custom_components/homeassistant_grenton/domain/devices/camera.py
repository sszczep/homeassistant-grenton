from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceCamera(BaseGrentonDevice):
    """Device for Camera widgets."""