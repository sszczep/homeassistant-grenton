"""Mapper for converting ValueDouble widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.roller_shutter_v3 import GrentonDeviceRollerShutterV3
from ..domain.state_object import GrentonStateObject
from ..domain.action import GrentonAction
from ..domain.entities.roller_shutter_v3 import GrentonEntityRollerShutterV3
from ..dto.widgets.roller_shutter_v3 import GrentonWidgetRollerShutterV3Dto


class DeviceRollerShutterV3Mapper:
    """Mapper for GrentonWidgetRollerShutterDto to GrentonDeviceRollerShutter."""

    @staticmethod
    def to_domain(dto: GrentonWidgetRollerShutterV3Dto, coordinator: GrentonCoordinator) -> GrentonDeviceRollerShutterV3:
        """Convert DTO to domain object."""
        device = GrentonDeviceRollerShutterV3(
            type=dto.type,
            id=dto.id,
            entities=[],
        )
        
        entity = GrentonEntityRollerShutterV3(
            coordinator=coordinator,
            id=dto.id,
            label=dto.label,
            cover_state=GrentonStateObject.from_dto(dto.object.state),
            cover_position=GrentonStateObject.from_dto(dto.object.position),
            set_position=GrentonAction.from_dto(dto.object.setPositionAction),
            cover_tilt_position=GrentonStateObject.from_dto(dto.object.lamelPosition) if dto.object.lamelMoveTimeout else None,
            set_tilt_position=GrentonAction.from_dto(dto.object.setLamelPositionAction) if dto.object.lamelMoveTimeout else None,
            stop=GrentonAction.from_dto(dto.object.stopAction) if dto.object.stopAction else None,
            device_info=device.device_info,
        )

        device.entities = [entity]
        return device
