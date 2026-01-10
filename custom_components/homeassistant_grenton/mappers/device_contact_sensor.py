"""Mapper for converting Contact Sensor widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.contact_sensor import GrentonDeviceContactSensor
from ..domain.action import GrentonAction
from ..domain.state_object import GrentonStateObject
from ..domain.entities.base import BaseGrentonEntity
from ..domain.entities.binary_sensor import GrentonEntityBinarySensor
from ..domain.entities.button import GrentonEntityButton
from ..dto.widgets.contact_sensor import GrentonWidgetContactSensorDto


class DeviceContactSensorMapper:
    """Mapper for GrentonWidgetContactSensorDto to GrentonDeviceContactSensor."""

    @staticmethod
    def to_domain(dto: GrentonWidgetContactSensorDto, coordinator: GrentonCoordinator) -> GrentonDeviceContactSensor:
        """Convert DTO to domain object."""
        device = GrentonDeviceContactSensor(
            type=dto.type,
            id=dto.id,
            entities=[],
        )
        
        entities: list[BaseGrentonEntity] = []

        binary_sensor = GrentonEntityBinarySensor(
            coordinator=coordinator,
            id=f"{dto.id}_binary_sensor",
            label=dto.label,
            reversed=dto.reverseState,
            state_object=GrentonStateObject.from_dto(dto.object.value),
            device_info=device.device_info,
        )

        entities.append(binary_sensor)

        if dto.object.clickAction is not None:
            button = GrentonEntityButton(
                coordinator=coordinator,
                id=f"{dto.id}_button",
                label=dto.label,
                action_click=GrentonAction.from_dto(dto.object.clickAction),
                device_info=device.device_info,
            )

            entities.append(button)

        device.entities = entities
        return device
