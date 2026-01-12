"""Mapper for converting ValueV2 widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.camera import GrentonDeviceCamera
from ..domain.entities.camera import GrentonEntityCamera
from ..dto.widgets.camera import GrentonWidgetCameraDto


class DeviceCameraMapper:
    """Mapper for GrentonWidgetCameraDto to GrentonDeviceCamera."""

    @staticmethod
    def to_domain(dto: GrentonWidgetCameraDto, coordinator: GrentonCoordinator) -> GrentonDeviceCamera:
        """Convert DTO to domain object."""
        device = GrentonDeviceCamera(
            type=dto.type,
            id=dto.id,
            entities=[],
        )
        
        entity = GrentonEntityCamera(
            coordinator=coordinator,
            id=f"{dto.id}_0",
            label=dto.components[0].label,
            stream=dto.components[0].value,
            device_info=device.device_info,
        )
        
        device.entities = [entity]
        return device
