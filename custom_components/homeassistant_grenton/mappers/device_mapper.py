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
from ..dto.widgets.slider import GrentonWidgetSliderDto
from ..dto.widgets.multisensor import GrentonWidgetMultisensorDto
from ..dto.widgets.roller_shutter import GrentonWidgetRollerShutterDto
from ..dto.widgets.roller_shutter_v3 import GrentonWidgetRollerShutterV3Dto
from ..dto.widgets.camera import GrentonWidgetCameraDto
from ..dto.mobile_interface import GrentonMobileInterfaceDto

from .device_value_v2 import DeviceValueV2Mapper
from .device_value_double import DeviceValueDoubleMapper
from .device_on_off import DeviceOnOffMapper
from .device_on_off_double import DeviceOnOffDoubleMapper
from .device_dimmer_v2 import DeviceDimmerV2Mapper
from .device_led import DeviceLedMapper
from .device_contact_sensor import DeviceContactSensorMapper
from .device_contact_sensor_double import DeviceContactSensorDoubleMapper
from .device_slider import DeviceSliderMapper
from .device_multisensor import DeviceMultisensorMapper
from .device_roller_shutter import DeviceRollerShutterMapper
from .device_roller_shutter_v3 import DeviceRollerShutterV3Mapper
from .device_camera import DeviceCameraMapper


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
        if isinstance(dto, GrentonWidgetContactSensorDoubleDto): 
            return DeviceContactSensorDoubleMapper.to_domain(dto, coordinator)
        if isinstance(dto, GrentonWidgetSliderDto): 
            return DeviceSliderMapper.to_domain(dto, coordinator)
        if isinstance(dto, GrentonWidgetMultisensorDto):
            return DeviceMultisensorMapper.to_domain(dto, coordinator)
        if isinstance(dto, GrentonWidgetRollerShutterDto): 
            return DeviceRollerShutterMapper.to_domain(dto, coordinator)
        if isinstance(dto, GrentonWidgetRollerShutterV3Dto): 
            return DeviceRollerShutterV3Mapper.to_domain(dto, coordinator)
        if isinstance(dto, GrentonWidgetCameraDto): # type: ignore
            return DeviceCameraMapper.to_domain(dto, coordinator)
        
        raise ValueError(f"Unknown widget type: {type(dto)}")

    @staticmethod
    def from_mobile_interface(dto: GrentonMobileInterfaceDto, coordinator: GrentonCoordinator) -> list[BaseGrentonDevice]:
        """Convert mobile interface DTO to list of devices."""
        widgets = [widget for page in dto.pages for widget in page.widgets]
        devices = [DeviceMapper.to_domain(widget, coordinator) for widget in widgets]
        return devices
