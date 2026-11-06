"""Thermostat (Grenton THERMOSTAT virtual object) as a climate entity.

Object features/methods used:
    get(6)  state (0 = off)          execute(0) start   execute(1) stop
    get(7)  direction (0 heat, 1 cool)   set(7, x)
    get(12) target temperature        set(3, t) point value, set(8, 0) leave hold mode
    get(14) current temperature
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo

from .base import BaseGrentonEntity
from ..action import GrentonActionAttributeNumeric, GrentonActionMethodNumeric
from ..enums import GrentonActionEventType
from ..state_object import GrentonAttributeValueObject


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class GrentonEntityThermostat(BaseGrentonEntity, ClimateEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(
        self,
        coordinator: Any,
        id: str,
        label: str,
        clu_id: str,
        object_name: str,
        device_info: DeviceInfo | None = None,
    ) -> None:
        ClimateEntity.__init__(self)
        BaseGrentonEntity.__init__(self, coordinator, id, label, device_info)

        def state(index: int) -> GrentonAttributeValueObject:
            return GrentonAttributeValueObject(clu_id=clu_id, object_name=object_name, index=str(index))

        self._state = state(6)
        self._direction = state(7)
        self._target = state(12)
        self._current = state(14)
        for obj in (self._state, self._direction, self._target, self._current):
            coordinator.register_component_state(obj)

        self._start = GrentonActionMethodNumeric(clu_id, object_name, GrentonActionEventType.ON, "0", index="0")
        self._stop = GrentonActionMethodNumeric(clu_id, object_name, GrentonActionEventType.OFF, "0", index="1")
        self._set_direction = GrentonActionAttributeNumeric(clu_id, object_name, GrentonActionEventType.CLICK, "0", index="7")
        self._leave_hold = GrentonActionAttributeNumeric(clu_id, object_name, GrentonActionEventType.CLICK, "0", index="8")
        self._set_point = GrentonActionAttributeNumeric(clu_id, object_name, GrentonActionEventType.CLICK, "0", index="3")

    def _value(self, obj: GrentonAttributeValueObject) -> Any:
        return self.coordinator.get_value_for_component(obj)

    @property
    def hvac_mode(self) -> HVACMode | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        state = _float(self._value(self._state))
        if state is None:
            return None
        if state == 0:
            return HVACMode.OFF
        return HVACMode.COOL if _float(self._value(self._direction)) == 1 else HVACMode.HEAT

    @property
    def target_temperature(self) -> float | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        return _float(self._value(self._target))

    @property
    def current_temperature(self) -> float | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        return _float(self._value(self._current))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.execute_action(self._leave_hold)
        await self.coordinator.execute_action(replace(self._set_point, value=str(float(temperature))))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.execute_action(self._stop)
            return
        direction = "1" if hvac_mode == HVACMode.COOL else "0"
        await self.coordinator.execute_action(self._start)
        await self.coordinator.execute_action(replace(self._set_direction, value=direction))

    async def async_turn_on(self) -> None:
        await self.coordinator.execute_action(self._start)

    async def async_turn_off(self) -> None:
        await self.coordinator.execute_action(self._stop)
