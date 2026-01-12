from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceContactSensor(BaseGrentonDevice):
    """Device for Contact Sensor widgets."""