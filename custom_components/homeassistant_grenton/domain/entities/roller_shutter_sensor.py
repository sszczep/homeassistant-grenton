from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity
from ..state_object import GrentonStateObject
from ...coordinator import GrentonCoordinator

class GrentonEntityRollerShutterSensor( # pyright: ignore[reportIncompatibleVariableOverride]
    BaseGrentonEntity,
    SensorEntity): 
    """Roller shutter sensor entity."""

    _attr_options = ["stopped", "opening", "closing", "locked", "unknown"]
    _attr_translation_key = "roller_shutter_state"

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        state_object: GrentonStateObject,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize multisensor sensor entity."""
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        SensorEntity.__init__(self)

        self.state_object = state_object
        
        # Register state with coordinator
        coordinator.register_component_state(state_object)

    @property
    def native_value(self): # pyright: ignore[reportIncompatibleVariableOverride]
        state = self.coordinator.get_value_for_component(self.state_object)
        if state == 0:
            return "stopped"
        elif state == 1:
            return "opening"
        elif state == 2:
            return "closing"
        elif state == 3:
            return "locked"
        return "unknown"

    @property
    def device_class(self) -> SensorDeviceClass | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        return SensorDeviceClass.ENUM
    