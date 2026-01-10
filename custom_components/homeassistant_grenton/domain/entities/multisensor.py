from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity
from ..state_object import GrentonStateObject
from ...coordinator import GrentonCoordinator

class GrentonEntityMultisensor( # pyright: ignore[reportIncompatibleVariableOverride]
    BaseGrentonEntity,
    SensorEntity): 
    """Multisensor sensor entity."""

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        device_class: SensorDeviceClass,
        unit_of_measurement: str,
        state_object: GrentonStateObject,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize multisensor sensor entity."""
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        SensorEntity.__init__(self)

        self._device_class = device_class
        self._unit_of_measurement = unit_of_measurement
        self.state_object = state_object
        
        # Register state with coordinator
        coordinator.register_component_state(state_object)

    @property
    def native_value(self): # pyright: ignore[reportIncompatibleVariableOverride]
        return self.coordinator.get_value_for_component(self.state_object)

    @property
    def device_class(self) -> SensorDeviceClass | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        return self._device_class

    @property
    def native_unit_of_measurement(self): # pyright: ignore[reportIncompatibleVariableOverride]
        return self._unit_of_measurement