from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceLed(BaseGrentonDevice):
    """Device for LED widgets."""