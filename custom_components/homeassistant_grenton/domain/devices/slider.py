from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceSlider(BaseGrentonDevice):
    """Device for Slider widgets."""