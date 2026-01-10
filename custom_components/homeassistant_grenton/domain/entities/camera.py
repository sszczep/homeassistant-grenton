from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity
from ...coordinator import GrentonCoordinator

class GrentonEntityCamera( # pyright: ignore[reportIncompatibleVariableOverride]
    BaseGrentonEntity,
    Camera): 
    """Camera entity."""

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        stream: str,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize camera entity."""
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)
        Camera.__init__(self)

        self._stream = stream

    @property
    def supported_features(self) -> CameraEntityFeature:  # pyright: ignore[reportIncompatibleVariableOverride]
        return CameraEntityFeature.STREAM
    
    @property
    def is_streaming(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        return True
    
    @property
    def use_stream_for_stills(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        return True
    
    async def stream_source(self) -> str: # pyright: ignore[reportIncompatibleVariableOverride]
        return self._stream  
