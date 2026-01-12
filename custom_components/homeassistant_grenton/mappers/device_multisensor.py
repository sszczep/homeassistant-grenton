"""Mapper for converting ValueV2 widget DTO to domain device."""

from homeassistant.components.sensor import SensorDeviceClass

from ..coordinator import GrentonCoordinator
from ..domain.devices.multisensor import GrentonDeviceMultisensor
from ..domain.state_object import GrentonStateObject
from ..domain.entities.multisensor import GrentonEntityMultisensor
from ..dto.widgets.multisensor import GrentonWidgetMultisensorDto


class DeviceMultisensorMapper:
    """Mapper for GrentonWidgetMultisensorDto to GrentonDeviceMultisensor."""

    @staticmethod
    def to_domain(dto: GrentonWidgetMultisensorDto, coordinator: GrentonCoordinator) -> GrentonDeviceMultisensor:
        """Convert DTO to domain object."""
        device = GrentonDeviceMultisensor(
            type=dto.type,
            id=dto.id,
            entities=[],
        )

        # objectAirCo2: GrentonObjectMultisensorDto
        # objectSound: GrentonObjectMultisensorDto
        # objectAirVoc: GrentonObjectMultisensorDto
        # objectLight: GrentonObjectMultisensorDto
        # objectPressure: GrentonObjectMultisensorDto
        # objectHumidity: GrentonObjectMultisensorDto
        # objectTemperature: GrentonObjectMultisensorDto

        entity_air_co2 = GrentonEntityMultisensor(
            coordinator=coordinator,
            id=f"{dto.id}_air_co2",
            label=dto.label,
            device_class=SensorDeviceClass.CO2,
            unit_of_measurement="ppm",
            state_object=GrentonStateObject.from_dto(dto.objectAirCo2.value),
            device_info=device.device_info,
        )
        
        entity_sound = GrentonEntityMultisensor(
            coordinator=coordinator,
            id=f"{dto.id}_sound",
            label=dto.label,
            device_class=SensorDeviceClass.SOUND_PRESSURE,
            unit_of_measurement="dB",
            state_object=GrentonStateObject.from_dto(dto.objectSound.value),
            device_info=device.device_info,
        )

        entity_air_voc = GrentonEntityMultisensor(
            coordinator=coordinator,
            id=f"{dto.id}_air_voc",
            label=dto.label,
            device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
            unit_of_measurement="ppb",
            state_object=GrentonStateObject.from_dto(dto.objectAirVoc.value),
            device_info=device.device_info,
        )

        entity_light = GrentonEntityMultisensor(
            coordinator=coordinator,
            id=f"{dto.id}_light",
            label=dto.label,
            device_class=SensorDeviceClass.ILLUMINANCE,
            unit_of_measurement="lx",
            state_object=GrentonStateObject.from_dto(dto.objectLight.value),
            device_info=device.device_info,
        )

        entity_pressure = GrentonEntityMultisensor(
            coordinator=coordinator,
            id=f"{dto.id}_pressure",
            label=dto.label,
            device_class=SensorDeviceClass.PRESSURE,
            unit_of_measurement="hPa",
            state_object=GrentonStateObject.from_dto(dto.objectPressure.value),
            device_info=device.device_info,
        )

        entity_humidity = GrentonEntityMultisensor(
            coordinator=coordinator,
            id=f"{dto.id}_humidity",
            label=dto.label,
            device_class=SensorDeviceClass.HUMIDITY,
            unit_of_measurement="%",
            state_object=GrentonStateObject.from_dto(dto.objectHumidity.value),
            device_info=device.device_info,
        )

        entity_temperature = GrentonEntityMultisensor(
            coordinator=coordinator,
            id=f"{dto.id}_temperature",
            label=dto.label,
            device_class=SensorDeviceClass.TEMPERATURE,
            unit_of_measurement="°C",
            state_object=GrentonStateObject.from_dto(dto.objectTemperature.value),
            device_info=device.device_info,
        )
        
        device.entities = [
            entity_air_co2,
            entity_sound,
            entity_air_voc,
            entity_light,
            entity_pressure,
            entity_humidity,
            entity_temperature,
        ]
        return device
