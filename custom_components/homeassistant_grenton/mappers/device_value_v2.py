"""Mapper for converting ValueV2 widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.value_v2 import GrentonDeviceValueV2
from ..domain.state_object import GrentonStateObject
from ..domain.entities.value import GrentonEntityValue
from ..dto.widgets.value_v2 import GrentonWidgetValueV2Dto


class DeviceValueV2Mapper:
    """Mapper for GrentonWidgetValueV2Dto to GrentonDeviceValueV2."""

    @staticmethod
    def to_domain(dto: GrentonWidgetValueV2Dto, coordinator: GrentonCoordinator) -> GrentonDeviceValueV2:
        """Convert DTO to domain object."""
        device = GrentonDeviceValueV2(
            type=dto.type,
            id=dto.id,
            entities=[],
        )
        
        entity = GrentonEntityValue(
            coordinator=coordinator,
            id=f"{dto.id}_0",
            label=dto.label,
            state_object=GrentonStateObject.from_dto(dto.object.value),
            device_info=device.device_info,
        )
        
        device.entities = [entity]
        return device
