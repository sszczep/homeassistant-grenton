from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceContactSensorDouble(BaseGrentonDevice):
    """Device for Contact Sensor Double widgets."""