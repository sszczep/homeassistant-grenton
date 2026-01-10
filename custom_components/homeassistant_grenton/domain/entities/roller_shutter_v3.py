from typing import Any
from homeassistant.components.cover import CoverEntity, CoverDeviceClass, CoverEntityFeature, ATTR_POSITION, ATTR_TILT_POSITION
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity
from ..action import GrentonAction
from ..state_object import GrentonStateObject
from ...coordinator import GrentonCoordinator
from ..utils.ranges import map_range


class GrentonEntityRollerShutterV3(BaseGrentonEntity, CoverEntity): # pyright: ignore[reportIncompatibleVariableOverride]
    """Roller shutter entity."""

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        cover_state: GrentonStateObject,
        cover_position: GrentonStateObject,
        set_position: GrentonAction,
        cover_tilt_position: GrentonStateObject | None = None,
        set_tilt_position: GrentonAction | None = None,
        stop: GrentonAction | None = None,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize roller shutter entity."""
        CoverEntity.__init__(self)
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)

        self.cover_state = cover_state
        self.cover_position = cover_position
        self.cover_tilt_position = cover_tilt_position
        self.set_position = set_position
        self.set_tilt_position = set_tilt_position
        self.stop = stop

        # Register state with coordinator
        coordinator.register_component_state(cover_state)
        coordinator.register_component_state(cover_position)
        if cover_tilt_position:
            coordinator.register_component_state(cover_tilt_position)

    @property
    def current_cover_position(self) -> int | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        value = self.coordinator.get_value_for_component(self.cover_position)
        if value is None:
            return None
        return int(value)
    
    @property
    def current_cover_tilt_position(self) -> int | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        if not self.cover_tilt_position:
            return None
        value = self.coordinator.get_value_for_component(self.cover_tilt_position)
        if value is None:
            return None
        value = map_range((0, 90), (0, 100), int(value))
        return int(100 - value)

    @property
    def is_closed(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        value = self.coordinator.get_value_for_component(self.cover_position)
        return value == 0
    
    @property
    def is_closing(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        value = self.coordinator.get_value_for_component(self.cover_state)
        return value == 2
    
    @property
    def is_opening(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        value = self.coordinator.get_value_for_component(self.cover_state)
        return value == 1
    
    async def async_open_cover(self, **kwargs: Any) -> None:  # pyright: ignore[reportIncompatibleVariableOverride]
        self.set_position.value = "100"
        await self.coordinator.execute_action(self.set_position)

    async def async_close_cover(self, **kwargs: Any) -> None:  # pyright: ignore[reportIncompatibleVariableOverride]
        self.set_position.value = "0"
        await self.coordinator.execute_action(self.set_position)

    async def async_set_cover_position(self, **kwargs: Any) -> None:  # pyright: ignore[reportIncompatibleVariableOverride]
        position = kwargs.get(ATTR_POSITION)
        if position is None:
            return
        self.set_position.value = str(position)
        await self.coordinator.execute_action(self.set_position)

    async def async_stop_cover(self, **kwargs: Any) -> None: # pyright: ignore[reportIncompatibleVariableOverride]
        if self.stop:
            await self.coordinator.execute_action(self.stop)

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:  # pyright: ignore[reportIncompatibleVariableOverride]
        if not self.set_tilt_position:
            return
        self.set_tilt_position.value = "0"
        await self.coordinator.execute_action(self.set_tilt_position)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:  # pyright: ignore[reportIncompatibleVariableOverride]
        if not self.set_tilt_position:
            return
        self.set_tilt_position.value = "90"
        await self.coordinator.execute_action(self.set_tilt_position)

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:  # pyright: ignore[reportIncompatibleVariableOverride]
        if not self.set_tilt_position:
            return
        position = kwargs.get(ATTR_TILT_POSITION)
        if position is None:
            return
        position = map_range((0, 100), (0, 90), int(position))
        self.set_tilt_position.value = str(int(90 - position))
        await self.coordinator.execute_action(self.set_tilt_position)

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None: # pyright: ignore[reportIncompatibleVariableOverride]
        if self.stop:
            await self.coordinator.execute_action(self.stop)

    @property
    def device_class(self) -> CoverDeviceClass:  # pyright: ignore[reportIncompatibleVariableOverride]
        return CoverDeviceClass.SHUTTER

    @property
    def supported_features(self) -> CoverEntityFeature:  # pyright: ignore[reportIncompatibleVariableOverride]
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.SET_POSITION
        if self.stop:
            features |= CoverEntityFeature.STOP
        if self.set_tilt_position:
            features |= (
                CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.SET_TILT_POSITION
            )
            if self.stop:
                features |= CoverEntityFeature.STOP_TILT
        return features  