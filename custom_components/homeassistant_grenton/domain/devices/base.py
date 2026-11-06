from abc import ABC
from dataclasses import dataclass

from homeassistant.helpers.device_registry import DeviceInfo

from ..entities.base import BaseGrentonEntity


@dataclass
class BaseGrentonDevice(ABC):
    type: str
    id: str
    entities: list[BaseGrentonEntity]
    name: str | None = None
    suggested_area: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return Home Assistant device info."""
        info = DeviceInfo(
            identifiers={("grenton", self.id)},
            manufacturer="Grenton",
            model=self.type,
        )
        if self.name:
            info["name"] = self.name
        else:
            # Fallback: generic, translated name of the widget type
            info["translation_key"] = self.type.lower()
        if self.suggested_area:
            info["suggested_area"] = self.suggested_area
        return info

    def apply_naming(self, name: str | None, suggested_area: str | None) -> None:
        """Set device name/area and propagate the device info to entities.

        Mappers hand entities a device_info snapshot, so it is refreshed here.
        An entity whose label equals the device name becomes the device's
        main entity (name=None) to avoid friendly names like "Lampa Lampa".
        """
        self.name = name
        self.suggested_area = suggested_area
        info = self.device_info
        for entity in self.entities:
            entity._attr_device_info = info  # pyright: ignore[reportPrivateUsage]
            entity.use_device_name = bool(name) and entity.label.strip() == name
