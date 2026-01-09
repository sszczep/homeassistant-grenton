"""Mapper for converting DimmerV2 widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.dimmer_v2 import GrentonDeviceDimmerV2
from ..domain.state_object import GrentonStateObject
from ..domain.action import GrentonAction
from ..domain.entities.dimmer import GrentonEntityDimmer
from ..dto.widgets.dimmer_v2 import GrentonWidgetDimmerV2Dto


class DeviceDimmerV2Mapper:
    """Mapper for GrentonWidgetDimmerV2Dto to GrentonDeviceDimmerV2."""

    @staticmethod
    def to_domain(dto: GrentonWidgetDimmerV2Dto, coordinator: GrentonCoordinator) -> GrentonDeviceDimmerV2:
        """Convert DTO to domain object."""
        device = GrentonDeviceDimmerV2(
            type=dto.type,
            id=dto.id,
            entities=[],
        )
        
        entity = GrentonEntityDimmer(
            coordinator=coordinator,
            id=f"{dto.id}_0",
            label=dto.label,
            min=dto.min,
            max=dto.max,
            precision=dto.precision,
            state_object=GrentonStateObject.from_dto(dto.object.value),
            action_on=GrentonAction.from_dto(dto.object.onAction),
            action_off=GrentonAction.from_dto(dto.object.offAction),
            action_set_value=GrentonAction.from_dto(dto.object.setValueAction),
            device_info=device.device_info,
        )

        device.entities = [entity]
        return device
