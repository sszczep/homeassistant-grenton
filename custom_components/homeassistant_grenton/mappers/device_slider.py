"""Mapper for converting ValueV2 widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.slider import GrentonDeviceSlider
from ..domain.state_object import GrentonStateObject
from ..domain.action import GrentonAction
from ..domain.entities.base import BaseGrentonEntity
from ..domain.entities.slider import GrentonEntitySlider
from ..domain.entities.button import GrentonEntityButton
from ..dto.widgets.slider import GrentonWidgetSliderDto


class DeviceSliderMapper:
    """Mapper for GrentonWidgetSliderDto to GrentonDeviceSlider."""

    @staticmethod
    def to_domain(dto: GrentonWidgetSliderDto, coordinator: GrentonCoordinator) -> GrentonDeviceSlider:
        """Convert DTO to domain object."""
        device = GrentonDeviceSlider(
            type=dto.type,
            id=dto.id,
            entities=[],
        )

        entities: list[BaseGrentonEntity] = []
        
        slider_entity = GrentonEntitySlider(
            coordinator=coordinator,
            id=f"{dto.id}_slider",
            label=dto.label,
            min=dto.min,
            max=dto.max,
            precision=dto.precision,
            state_object=GrentonStateObject.from_dto(dto.object.value),
            action_set_value=GrentonAction.from_dto(dto.object.setValueAction),
            device_info=device.device_info,
        )

        entities.append(slider_entity)

        if dto.object.clickAction:
            button_entity = GrentonEntityButton(
                coordinator=coordinator,
                id=f"{dto.id}_button",
                label=dto.label,
                action_click=GrentonAction.from_dto(dto.object.clickAction),
                device_info=device.device_info,
            )

            entities.append(button_entity)
        
        device.entities = entities
        return device
