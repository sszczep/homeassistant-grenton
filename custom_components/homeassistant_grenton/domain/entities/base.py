from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.core import callback

from ...coordinator import GrentonCoordinator


class BaseGrentonEntity(CoordinatorEntity[GrentonCoordinator]):
    """Base entity class that inherits CoordinatorEntity for automatic updates."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize entity with coordinator and device info."""
        super().__init__(coordinator)
        self.label = label
        self._attr_unique_id = id
        self._attr_device_info = device_info

    @property
    def name(self) -> str: # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the name of the sensor."""
        return self.label

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator.
        
        This is called automatically by CoordinatorEntity when the coordinator
        data is updated (either on schedule or when async_refresh is called).
        """
        self.async_write_ha_state()