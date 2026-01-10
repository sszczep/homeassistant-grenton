from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceMultisensor(BaseGrentonDevice):
    """Device for Multisensor widgets."""