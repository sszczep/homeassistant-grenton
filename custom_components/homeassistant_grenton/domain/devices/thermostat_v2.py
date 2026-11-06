"""Device for a THERMOSTAT_V2 mobile widget."""

from dataclasses import dataclass

from .base import BaseGrentonDevice


@dataclass
class GrentonDeviceThermostatV2(BaseGrentonDevice):
    """A thermostat with climate controls and a read-only schedule sensor."""
