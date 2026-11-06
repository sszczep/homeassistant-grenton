"""Connection diagnostics derived from existing traffic, with no CLU bindings."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from ...coordinator import GrentonCoordinator
from ..clu import GrentonClu
from .clu import clu_device_info


class CluConnectionDiagnostic(Entity):
    """Remain available during outages so the device page can explain them."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(
        self, coordinator: GrentonCoordinator, clu: GrentonClu, key: str
    ) -> None:
        self.coordinator = coordinator
        self.clu = clu
        self._attr_unique_id = f"clu_{clu.id}_{key.removeprefix('clu_')}"
        self._attr_translation_key = key
        self._attr_device_info = clu_device_info(clu)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self.coordinator.health_update_signal(self.clu.id),
                self._update,
            )
        )

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()


class CluConnection(CluConnectionDiagnostic, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.connection_health[self.clu.id].connected


class CluRequestTimeouts(CluConnectionDiagnostic, SensorEntity):
    _attr_icon = "mdi:timer-alert-outline"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self) -> int:
        return self.coordinator.connection_health[self.clu.id].request_timeouts


class CluSubscriptions(CluConnectionDiagnostic, SensorEntity):
    _attr_icon = "mdi:lan-connect"

    @property
    def native_value(self) -> int:
        return self.coordinator.subscription_count(self.clu.id)


def connection_diagnostics(
    coordinator: GrentonCoordinator, clu: GrentonClu
) -> list[Entity]:
    return [
        entity(coordinator, clu, key)
        for entity, key in (
            (CluConnection, "clu_connection"),
            (CluRequestTimeouts, "clu_request_timeouts"),
            (CluSubscriptions, "clu_subscriptions"),
        )
    ]
