"""Mapper for converting Contact Sensor Double widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.contact_sensor_double import GrentonDeviceContactSensorDouble
from ..domain.action import GrentonAction
from ..domain.state_object import GrentonStateObject
from ..domain.entities.base import BaseGrentonEntity
from ..domain.entities.binary_sensor import GrentonEntityBinarySensor
from ..domain.entities.button import GrentonEntityButton
from ..dto.widgets.contact_sensor_double import GrentonWidgetContactSensorDoubleDto


class DeviceContactSensorDoubleMapper:
    """Mapper for GrentonWidgetContactSensorDoubleDto to GrentonDeviceContactSensorDouble."""

    @staticmethod
    def to_domain(dto: GrentonWidgetContactSensorDoubleDto, coordinator: GrentonCoordinator) -> GrentonDeviceContactSensorDouble:
        """Convert DTO to domain object."""
        device = GrentonDeviceContactSensorDouble(
            type=dto.type,
            id=dto.id,
            entities=[],
        )
        
        entities: list[BaseGrentonEntity] = []

        binary_sensor_left = GrentonEntityBinarySensor(
            coordinator=coordinator,
            id=f"{dto.id}_binary_sensor_left",
            label=dto.componentLeft.label,
            reversed=dto.componentLeft.reverseState,
            state_object=GrentonStateObject.from_dto(dto.componentLeft.object.value),
            device_info=device.device_info,
        )

        entities.append(binary_sensor_left)

        binary_sensor_right = GrentonEntityBinarySensor(
            coordinator=coordinator,
            id=f"{dto.id}_binary_sensor_right",
            label=dto.componentRight.label,
            reversed=dto.componentRight.reverseState,
            state_object=GrentonStateObject.from_dto(dto.componentRight.object.value),
            device_info=device.device_info,
        )

        entities.append(binary_sensor_right)

        if dto.componentLeft.object.clickAction is not None:
            button = GrentonEntityButton(
                coordinator=coordinator,
                id=f"{dto.id}_button_left",
                label=dto.componentLeft.label,
                action_click=GrentonAction.from_dto(dto.componentLeft.object.clickAction),
                device_info=device.device_info,
            )

            entities.append(button)

        if dto.componentRight.object.clickAction is not None:
            button = GrentonEntityButton(
                coordinator=coordinator,
                id=f"{dto.id}_button_right",
                label=dto.componentRight.label,
                action_click=GrentonAction.from_dto(dto.componentRight.object.clickAction),
                device_info=device.device_info,
            )

            entities.append(button)

        device.entities = entities
        return device
