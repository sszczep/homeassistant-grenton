"""Mapper for converting OnOffDouble widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.action import GrentonAction
from ..domain.devices.on_off_double import GrentonDeviceOnOffDouble
from ..domain.entities.base import BaseGrentonEntity
from ..domain.entities.bistable_switch import GrentonEntityBistableSwitch
from ..domain.entities.on_off import GrentonEntityOnOffLight, configured_on_off_type
from ..domain.enums import GrentonActionEventType
from ..domain.state_object import GrentonStateObject
from ..dto.widgets.on_off_double import GrentonWidgetOnOffDoubleDto


class DeviceOnOffDoubleMapper:
    """Mapper for GrentonWidgetOnOffDoubleDto to GrentonDeviceOnOffDouble."""

    @staticmethod
    def to_domain(dto: GrentonWidgetOnOffDoubleDto, coordinator: GrentonCoordinator) -> GrentonDeviceOnOffDouble:
        """Convert DTO to domain object."""
        device = GrentonDeviceOnOffDouble(
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
                unique_id = f"{dto.id}_{component.rowId}"
                entity_class = (
                    GrentonEntityOnOffLight
                    if configured_on_off_type(
                        coordinator,
                        unique_id,
                        label=component.label,
                        icon=component.icon or dto.icon,
                    )
                    == "light"
                    else GrentonEntityBistableSwitch
                )
                entity = entity_class(
                    coordinator=coordinator,
                    id=unique_id,
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
