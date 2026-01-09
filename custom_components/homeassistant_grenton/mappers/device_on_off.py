"""Mapper for converting OnOff widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.on_off import GrentonDeviceOnOff
from ..domain.enums import GrentonActionEventType
from ..domain.action import GrentonAction
from ..domain.state_object import GrentonStateObject
from ..domain.entities.base import BaseGrentonEntity
from ..domain.entities.bistable_switch import GrentonEntityBistableSwitch
from ..dto.widgets.on_off import GrentonWidgetOnOffDto


class DeviceOnOffMapper:
    """Mapper for GrentonWidgetOnOffDto to GrentonDeviceOnOff."""

    @staticmethod
    def to_domain(dto: GrentonWidgetOnOffDto, coordinator: GrentonCoordinator) -> GrentonDeviceOnOff:
        """Convert DTO to domain object."""
        device = GrentonDeviceOnOff(
            type=dto.type,
            id=dto.id,
            entities=[],
        )
        
        entities: list[BaseGrentonEntity] = []
        for component in dto.components:
            # Find ON and OFF actions
            action_on: GrentonAction | None = None
            action_off: GrentonAction | None = None
            for action_dto in component.actions or []:
                action = GrentonAction.from_dto(action_dto)
                
                if action.event == GrentonActionEventType.ON:
                    action_on = action
                elif action.event == GrentonActionEventType.OFF:
                    action_off = action
                    
            # Ensure both actions are present
            if action_on and action_off:
                entity = GrentonEntityBistableSwitch(
                    coordinator=coordinator,
                    id=f"{dto.id}_{component.rowId}",
                    label=component.label,
                    unit=component.unit,
                    state_object=GrentonStateObject.from_dto(component.state),
                    action_on=action_on,
                    action_off=action_off,
                    device_info=device.device_info,
                )

                entities.append(entity)

        device.entities = entities
        return device
