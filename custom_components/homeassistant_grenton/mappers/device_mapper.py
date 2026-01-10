"""Mapper for dispatching widget DTOs to appropriate device mappers."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.base import BaseGrentonDevice
from ..dto.widgets.union import GrentonWidgetUnionDto
from ..dto.widgets.value_v2 import GrentonWidgetValueV2Dto
from ..dto.widgets.value_double import GrentonWidgetValueDoubleDto
from ..dto.widgets.on_off import GrentonWidgetOnOffDto
from ..dto.widgets.on_off_double import GrentonWidgetOnOffDoubleDto
from ..dto.widgets.dimmer_v2 import GrentonWidgetDimmerV2Dto
from ..dto.widgets.led import GrentonWidgetLedDto
from ..dto.widgets.contact_sensor import GrentonWidgetContactSensorDto
from ..dto.widgets.contact_sensor_double import GrentonWidgetContactSensorDoubleDto
from ..dto.mobile_interface import GrentonMobileInterfaceDto

from .device_value_v2 import DeviceValueV2Mapper
from .device_value_double import DeviceValueDoubleMapper
from .device_on_off import DeviceOnOffMapper
from .device_on_off_double import DeviceOnOffDoubleMapper
from .device_dimmer_v2 import DeviceDimmerV2Mapper
from .device_led import DeviceLedMapper
from .device_contact_sensor import DeviceContactSensorMapper
from .device_contact_sensor_double import DeviceContactSensorDoubleMapper


class DeviceMapper:
    """Router that dispatches widget DTOs to appropriate device mappers."""

    @staticmethod
    def to_domain(dto: GrentonWidgetUnionDto, coordinator: GrentonCoordinator) -> BaseGrentonDevice:
        """Convert widget DTO to domain device using appropriate mapper."""
        if isinstance(dto, GrentonWidgetValueV2Dto):
            return DeviceValueV2Mapper.to_domain(dto, coordinator)
        if isinstance(dto, GrentonWidgetValueDoubleDto):
            return DeviceValueDoubleMapper.to_domain(dto, coordinator)
        if isinstance(dto, GrentonWidgetOnOffDto):
            return DeviceOnOffMapper.to_domain(dto, coordinator)
        if isinstance(dto, GrentonWidgetOnOffDoubleDto):
            return DeviceOnOffDoubleMapper.to_domain(dto, coordinator)
        if isinstance(dto, GrentonWidgetDimmerV2Dto):  
            return DeviceDimmerV2Mapper.to_domain(dto, coordinator)
        if isinstance(dto, GrentonWidgetLedDto):
            return DeviceLedMapper.to_domain(dto, coordinator)
        if isinstance(dto, GrentonWidgetContactSensorDto):
            return DeviceContactSensorMapper.to_domain(dto, coordinator)
        if isinstance(dto, GrentonWidgetContactSensorDoubleDto): # type: ignore
            return DeviceContactSensorDoubleMapper.to_domain(dto, coordinator)
        
        raise ValueError(f"Unknown widget type: {type(dto)}")

    @staticmethod
    def from_mobile_interface(dto: GrentonMobileInterfaceDto, coordinator: GrentonCoordinator) -> list[BaseGrentonDevice]:
        """Convert mobile interface DTO to list of devices."""
        widgets = [widget for page in dto.pages for widget in page.widgets]
        devices = [DeviceMapper.to_domain(widget, coordinator) for widget in widgets]
        return devices
