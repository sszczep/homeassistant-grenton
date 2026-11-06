from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...coordinator import GrentonCoordinator
from ..entity_references import state_reference
from ..state_object import GrentonStateObject

# options key: {unique_id: {"name": str, "precision": int}}
# "name" is applied as the entity registry name (see entity_settings.apply_name_overrides)
CONF_ENTITY_OVERRIDES = "entity_overrides"


class GrentonStateEntity(CoordinatorEntity[GrentonCoordinator]):
    """Share realtime availability policy across widgets and built-in CLU values."""

    @property
    def state_sources(self) -> list[GrentonStateObject]:
        """Most entities read one source; multi-source entities override this."""
        state = getattr(self, "state_object", None)
        return [state] if isinstance(state, GrentonStateObject) else []

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.states_available(
            self.state_sources
        )


class BaseGrentonEntity(GrentonStateEntity):
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

    def _register_state(self, state: GrentonStateObject) -> None:
        self.coordinator.register_component_state(state)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose a compact source without copying editor configuration."""
        attributes = dict(super().extra_state_attributes or {})
        state = getattr(self, "state_object", None)
        if isinstance(state, GrentonStateObject):
            attributes.update(state_reference(state))
        return attributes

    # --- user overrides from the import flow / "Entity names" options -----
    def _overrides(self) -> dict[str, Any]:
        entry = getattr(self.coordinator, "config_entry", None)
        options = getattr(entry, "options", None) or {}
        overrides = (options.get(CONF_ENTITY_OVERRIDES) or {}).get(self.unique_id or "")
        return overrides if isinstance(overrides, dict) else {}

    @property
    def suggested_display_precision(self) -> int | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        precision = self._overrides().get("precision")
        if isinstance(precision, int) and not isinstance(precision, bool):
            return precision
        return getattr(super(), "suggested_display_precision", None)

    @property
    def name(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the name of the sensor."""
        if (
            self.platform_data
            and self.translation_key
            and isinstance(translated := super().name, str)
        ):
            return translated
        return None if getattr(self, "_use_device_name", False) else self.label

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator.

        This is called automatically by CoordinatorEntity when the coordinator
        data is updated (either on schedule or when async_refresh is called).
        """
        self.async_write_ha_state()
