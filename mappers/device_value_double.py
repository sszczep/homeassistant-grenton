"""Mapper for converting ValueDouble widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.value_double import GrentonDeviceValueDouble
from ..domain.state_object import GrentonStateObject
from ..domain.entities.value import GrentonEntityValue
from ..dto.widgets.value_double import GrentonWidgetValueDoubleDto


class DeviceValueDoubleMapper:
    """Mapper for GrentonWidgetValueDoubleDto to GrentonDeviceValueDouble."""

    @staticmethod
    def to_domain(dto: GrentonWidgetValueDoubleDto, coordinator: GrentonCoordinator) -> GrentonDeviceValueDouble:
        """Convert DTO to domain object."""
        device = GrentonDeviceValueDouble(
            type=dto.type,
            id=dto.id,
            entities=[],
        )
        
        entity_left = GrentonEntityValue(
            coordinator=coordinator,
            id=f"{dto.id}_0",
            label=dto.componentLeft.label,
            state_object=GrentonStateObject.from_dto(dto.componentLeft.object.value),
            device_info=device.device_info,
        )

        entity_right = GrentonEntityValue(
            coordinator=coordinator,
            id=f"{dto.id}_1",
            label=dto.componentRight.label,
            state_object=GrentonStateObject.from_dto(dto.componentRight.object.value),
            device_info=device.device_info,
        )

        device.entities = [entity_left, entity_right]
        return device
