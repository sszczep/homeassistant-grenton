"""A discovered CLU controller and its parameterized script calls."""

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN
from ...coordinator import GrentonCoordinator
from ..action import GrentonActionScript
from ..clu import GrentonClu
from ..enums import GrentonActionEventType
from ..scene_arguments import argument_expressions


def clu_device_info(clu: GrentonClu) -> DeviceInfo:
    """Share the controller's device identity with its built-in entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"clu_{clu.id}")},
        manufacturer="Grenton",
        model=clu.device_type or "CLU",
        name=clu.name,
        serial_number=clu.serial_number,
    )


class GrentonCluEntity(CoordinatorEntity[GrentonCoordinator], SensorEntity):
    """Identify the CLU independently of any mobile-interface widgets."""

    _attr_has_entity_name = True
    _attr_translation_key = "clu_controller"
    _attr_icon = "mdi:server"

    def __init__(self, coordinator: GrentonCoordinator, clu: GrentonClu) -> None:
        super().__init__(coordinator)
        self.clu = clu
        self._attr_unique_id = f"clu_{clu.id}"
        self._attr_native_value = clu.serial_number
        self._attr_device_info = clu_device_info(clu)
        self._attr_extra_state_attributes = {
            "clu_id": clu.id,
            "ip": clu.ip,
            "port": clu.port,
        }

    async def async_run_script(
        self, script: str, arguments: list[dict[str, Any]]
    ) -> None:
        """Run a named script on this CLU with positional typed arguments."""
        action = GrentonActionScript(
            clu_id=self.clu.id,
            object_name=script,
            event=GrentonActionEventType.CLICK,
            value=", ".join(argument_expressions(arguments)),
        )
        await self.coordinator.execute_action(action, raise_on_error=True)
