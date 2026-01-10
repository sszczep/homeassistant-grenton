"""Mapper for converting DimmerV2 widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.led import GrentonDeviceLed
from ..domain.state_object import GrentonStateObject
from ..domain.action import GrentonAction
from ..domain.entities.led import GrentonEntityLed
from ..domain.enums import GrentonActionEventType

from ..dto.widgets.led import GrentonWidgetLedDto
from ..dto.components.led import GrentonComponentLedButtonDto, GrentonComponentLedHueDto, GrentonComponentLedSaturationDto, GrentonComponentLedBrightnessDto


class DeviceLedMapper:
    """Mapper for GrentonWidgetLedDto to GrentonDeviceLed."""

    @staticmethod
    def to_domain(dto: GrentonWidgetLedDto, coordinator: GrentonCoordinator) -> GrentonDeviceLed:
        """Convert DTO to domain object."""
        device = GrentonDeviceLed(
            type=dto.type,
            id=dto.id,
            entities=[],
        )

        on_off_component: GrentonComponentLedButtonDto | None = None
        hue_component: GrentonComponentLedHueDto | None = None
        saturation_component: GrentonComponentLedSaturationDto | None = None
        brightness_component: GrentonComponentLedBrightnessDto | None = None

        for component in dto.components:
            if component.type == "BUTTON_BISTABLE":
                on_off_component = component
            elif component.type == "SLIDER_HUE":
                hue_component = component
            elif component.type == "SLIDER_SATURATION":
                saturation_component = component
            elif component.type == "SLIDER_BRIGHTNESS":
                brightness_component = component

        if not on_off_component or not hue_component or not saturation_component or not brightness_component:
            return device  # Incomplete LED components, return device without entities
        
        action_on: GrentonAction | None = None
        action_off: GrentonAction | None = None
        for action_dto in on_off_component.actions or []:
            action = GrentonAction.from_dto(action_dto)
            
            if action.event == GrentonActionEventType.ON:
                action_on = action
            elif action.event == GrentonActionEventType.OFF:
                action_off = action

        if not action_on or not action_off:
            return device  # Incomplete LED button actions, return device without entities
        
        entity = GrentonEntityLed(
            coordinator=coordinator,
            id=f"{dto.id}_0",
            label=on_off_component.label,
            state_object=GrentonStateObject.from_dto(on_off_component.state),
            action_on=action_on,
            action_off=action_off,
            hue_action=GrentonAction.from_dto(hue_component.actions[0]),
            hue_state_object=GrentonStateObject.from_dto(hue_component.state),
            hue_range=(hue_component.range.min, hue_component.range.max),
            saturation_action=GrentonAction.from_dto(saturation_component.actions[0]),
            saturation_state_object=GrentonStateObject.from_dto(saturation_component.state),
            saturation_range=(saturation_component.range.min, saturation_component.range.max),
            brightness_action=GrentonAction.from_dto(brightness_component.actions[0]),
            brightness_state_object=GrentonStateObject.from_dto(brightness_component.state),
            brightness_range=(brightness_component.range.min, brightness_component.range.max),
            device_info=device.device_info,
        )

        device.entities = [entity]
        return device
