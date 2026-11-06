from abc import ABC
from dataclasses import dataclass

from homeassistant.helpers.device_registry import DeviceInfo

from ..entities.base import BaseGrentonEntity


@dataclass
class BaseGrentonDevice(ABC):
    type: str
    id: str
    entities: list[BaseGrentonEntity]
    # Set from the import flow / manual objects; None keeps the label-based name
    custom_name: str | None = None
    suggested_area: str | None = None

    @property
    def default_name(self) -> str:
        """Summarize the widget using its distinct entity labels."""
        labels = list(
            dict.fromkeys(
                entity.label.strip() for entity in self.entities if entity.label.strip()
            )
        )
        if not labels:
            return f"{self.type} ({self.id})"
        name = " · ".join(labels[:2])
        if len(labels) > 2:
            name += f" (+{len(labels) - 2})"
        return name

    @property
    def name(self) -> str:
        return (self.custom_name or "").strip() or self.default_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return Home Assistant device info."""
        info = DeviceInfo(
            identifiers={("grenton", self.id)},
            manufacturer="Grenton",
            model=self.type,
            name=self.name,
        )
        if self.suggested_area:
            info["suggested_area"] = self.suggested_area
        return info

    def apply_naming(self, custom_name: str | None, suggested_area: str | None) -> None:
        """Set an optional custom name/area and refresh the entities' device info.

        Mappers hand entities a device_info snapshot, so it is refreshed here.
        The sole entity of a device follows the device name (HA main entity).
        """
        self.custom_name = custom_name
        self.suggested_area = suggested_area
        info = self.device_info
        for entity in self.entities:
            entity._attr_device_info = info  # pyright: ignore[reportPrivateUsage]
            entity._use_device_name = len(self.entities) == 1  # pyright: ignore[reportAttributeAccessIssue]
