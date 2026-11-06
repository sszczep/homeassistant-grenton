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
        self.use_device_name = False
        self._attr_unique_id = id
        self._attr_device_info = device_info

    @property
    def name(self) -> str | None: # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the entity name (None = use the device name)."""
        if self.use_device_name:
            return None
        return self.label

    @property
    def clu_ids(self) -> set[str]:
        """CLUs this entity talks to (from its state objects and actions)."""
        ids: set[str] = set()
        for value in vars(self).values():
            clu_id = getattr(value, "clu_id", None)
            if isinstance(clu_id, str):
                ids.add(clu_id)
        return ids

    @property
    def available(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Unavailable when the coordinator failed or any of its CLUs is offline."""
        if not super().available:
            return False
        check = getattr(self.coordinator, "is_clu_available", None)
        if check is None:
            return True
        return all(check(clu_id) for clu_id in self.clu_ids)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator.
        
        This is called automatically by CoordinatorEntity when the coordinator
        data is updated (either on schedule or when async_refresh is called).
        """
        self.async_write_ha_state()