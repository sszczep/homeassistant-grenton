from abc import ABC
from dataclasses import dataclass

from homeassistant.helpers.device_registry import DeviceInfo

from ..entities.base import BaseGrentonEntity


@dataclass
class BaseGrentonDevice(ABC):
    type: str
    id: str
    entities: list[BaseGrentonEntity]

    @property
    def device_info(self) -> DeviceInfo:
        """Return Home Assistant device info."""
        return DeviceInfo(
            identifiers={("grenton", self.id)},
            manufacturer="Grenton",
            model=self.type,
            translation_key=self.type.lower(),
        )