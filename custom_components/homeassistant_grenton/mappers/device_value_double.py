"""Mapper for converting ValueDouble widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.value_double import GrentonDeviceValueDouble
from ..domain.state_object import GrentonStateObject
from ..domain.entities.value_v2 import value_v2_entity
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
        
        device.entities = [
            value_v2_entity(
                coordinator=coordinator,
                id=f"{dto.id}_{index}",
                label=component.label,
                state_object=GrentonStateObject.from_dto(component.object.value),
                value_type=component.valueType,
                device_info=device.device_info,
            )
            for index, component in enumerate((dto.componentLeft, dto.componentRight))
        ]
        return device
