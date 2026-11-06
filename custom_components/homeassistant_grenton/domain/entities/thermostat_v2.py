"""Heating, optional cooling and schedules for Grenton THERMOSTAT_V2 widgets."""

import asyncio
import logging
import math
from dataclasses import replace
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate.const import ATTR_HVAC_MODE
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo

from ...coordinator import GrentonCoordinator
from ..action import GrentonAction
from ..state_object import GrentonStateObject
from ..thermostat_schedule import ThermostatSchedule, decode_schedule, encode_schedule
from .base import BaseGrentonEntity
from .configurable import ConfigurableEntity
from .thermostat_configuration import (
    GrentonThermostatConfigurationSchema,
    schedule_sections,
    validate_limits,
)

_LOGGER = logging.getLogger(__name__)

MODE_VALUES = {HVACMode.HEAT: 0, HVACMode.COOL: 0, HVACMode.AUTO: 2}


class GrentonEntityThermostatV2(
    BaseGrentonEntity,
    ClimateEntity,
    ConfigurableEntity[GrentonThermostatConfigurationSchema],
):
    """A thermostat with manual heating/cooling and CLU schedule operation."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_supported_features = (
        ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    # BaseGrentonEntity always assigns the widget's non-null ID.
    unique_id: str

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        id: str,
        label: str,
        states: dict[str, GrentonStateObject],
        actions: dict[str, GrentonAction],
        device_info: DeviceInfo | None = None,
        cooling_detected: bool = False,
    ) -> None:
        super().__init__(coordinator, id, label, device_info)
        self.states = states
        self.actions = actions
        self._cooling_detected = cooling_detected
        ConfigurableEntity.__init__(self)
        self._command_lock = asyncio.Lock()
        self._last_schedule_status: str | None = None
        for name, state in states.items():
            if name == "scheduleData":
                coordinator.register_component_state(
                    state,
                    large_value=True,
                    read_mode="slow",
                    poll_condition=lambda: (
                        self.schedule_polling_enabled
                        and self.following_schedule is True
                    ),
                )
            elif name in (
                "currentTemperature",
                "targetTemperature",
                "minTemperature",
                "maxTemperature",
            ):
                coordinator.register_component_state(state, read_mode="slow")
            else:
                coordinator.register_component_state(state)

    @property
    def state_sources(self) -> list[GrentonStateObject]:
        return list(self.states.values())

    @property
    def name(self) -> None:
        # This remains the main entity when the read-only schedule is added.
        return None

    @property
    def decoded_schedule(self) -> ThermostatSchedule | None:
        data, maximum = self._value("scheduleData"), self._number("maxTemperature")
        if isinstance(data, str) and maximum is not None:
            try:
                return decode_schedule(data, maximum)
            except ValueError:
                pass
        return None

    @property
    def schedule_status(self) -> str:
        data, maximum = self._value("scheduleData"), self._number("maxTemperature")
        if not isinstance(data, str) or not data or maximum is None:
            return "Waiting for schedule data and maximum temperature from the CLU"
        try:
            decode_schedule(data, maximum)
        except ValueError as error:
            return str(error)
        return "ready"

    def _log_context(self, *bindings: str) -> str:
        """Identify both the HA device and the actual Grenton read targets."""
        device = self.device_entry
        device_name = (
            ((device.name_by_user or device.name) if device is not None else None)
            or (self.device_info or {}).get("name")
            or self.label
        )
        parts = [f"device={device_name!r}", f"widget={self.unique_id}"]
        if self.entity_id:
            parts.append(f"entity={self.entity_id}")
        for name in bindings:
            if (state := self.states.get(name)) is None:
                continue
            source = state.source_attributes
            target = (
                f"variable:{source['variable_name']}"
                if source["call_type"] == "VARIABLE"
                else f"{source['object_name']}.{source['index']}"
            )
            parts.append(f"{name}={source['clu_id']}/{target}")
        return ", ".join(parts)

    def _analyse_schedule(self) -> None:
        status = self.schedule_status
        if status != self._last_schedule_status:
            self._last_schedule_status = status
            if status == "ready":
                _LOGGER.debug(
                    "[%s] CLU weekly schedule decoded successfully",
                    self._log_context("scheduleData", "maxTemperature"),
                )
            elif self._value("scheduleData") is None and not (
                self.schedule_polling_enabled and self.following_schedule is True
            ):
                _LOGGER.debug(
                    "[%s] Schedule not loaded; automatic synchronization is paused",
                    self._log_context("scheduleData"),
                )
            else:
                _LOGGER.warning(
                    "[%s] Schedule unavailable: %s",
                    self._log_context("scheduleData", "maxTemperature"),
                    status,
                )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._analyse_schedule()

    async def async_prepare_configuration(self) -> None:
        """Read a fresh schedule and limits only when opening the editor."""
        if not await self._refresh_schedule():
            raise HomeAssistantError(
                "Could not load the thermostat schedule and limits"
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._analyse_schedule()
        super()._handle_coordinator_update()

    @property
    def following_schedule(self) -> bool | None:
        state, mode = self._number("state"), self._number("mode")
        if state == 0 or mode in (0, 1, 3):
            return False
        if state == 1 and mode == 2:
            return True
        return None

    @property
    def cooling_enabled(self) -> bool:
        return self._config.get("cooling_enabled", self._cooling_detected) is True

    @property
    def schedule_polling_enabled(self) -> bool:
        return self._config.get("schedule_polling_enabled", True) is True

    @property
    def hvac_modes(self) -> list[HVACMode]:
        return [
            HVACMode.OFF,
            HVACMode.HEAT,
            *([HVACMode.COOL] if self.cooling_enabled else []),
            HVACMode.AUTO,
        ]

    def default_config(self) -> dict[str, Any]:
        return {
            "cooling_enabled": self._cooling_detected,
            "schedule_polling_enabled": True,
        }

    def _get_schema_instance(self) -> GrentonThermostatConfigurationSchema:
        minimum, maximum = (
            self._number("minTemperature"),
            self._number("maxTemperature"),
        )
        settings: dict[str, Any] = {
            "cooling_available": "controlDirection" in self.states
            and "setControlDirectionAction" in self.actions,
            "schedule_available": False,
        }
        sections: list[dict[str, Any]] = []
        direction = self.control_direction_name
        if direction is not None:
            settings["direction"] = direction
        data = self._value("scheduleData")
        if minimum is not None and maximum is not None and isinstance(data, str):
            try:
                sections = schedule_sections(decode_schedule(data, maximum).periods())
            except ValueError:
                pass
            else:
                settings.update(
                    schedule_available=minimum < maximum,
                    minimum=minimum,
                    maximum=maximum,
                )
        settings["limits_available"] = settings["schedule_available"] and all(
            name in self.actions
            for name in ("setMinTemperatureAction", "setMaxTemperatureAction")
        )
        return GrentonThermostatConfigurationSchema(settings, sections)

    async def apply_configuration(self, user_input: dict[str, Any]) -> dict[str, Any]:
        # Keep the CLU authoritative: do not persist a second copy of its schedule.
        direction = user_input.get("control_direction")
        if direction is not None and (
            direction not in ("heating", "cooling") or not user_input["cooling_enabled"]
        ):
            raise ServiceValidationError(
                "Enable cooling before selecting its direction"
            )
        async with self._command_lock:
            if "schedule" in user_input or "limits" in user_input:
                await self._set_schedule_and_limits(
                    user_input.get("schedule"), user_input.get("limits")
                )
            if direction is not None:
                await self._execute(
                    "setControlDirectionAction", "1" if direction == "cooling" else "0"
                )
        options = await ConfigurableEntity.apply_configuration(
            self,
            {
                "cooling_enabled": user_input["cooling_enabled"],
                "schedule_polling_enabled": user_input.get(
                    "schedule_polling_enabled", self.schedule_polling_enabled
                ),
            },
        )
        if self.hass is not None:
            self.async_write_ha_state()
        return options

    def _value(self, name: str) -> Any:
        state = self.states.get(name)
        return (
            self.coordinator.get_value_for_component(state)
            if state is not None
            else None
        )

    def _direction(self) -> float | None:
        direction = self._number("controlDirection")
        # Preserve heating-only interfaces before direction feedback arrives.
        return 0 if direction is None and not self.cooling_enabled else direction

    @property
    def control_direction_name(self) -> str | None:
        direction = self._number("controlDirection")
        return "heating" if direction == 0 else "cooling" if direction == 1 else None

    def _number(self, name: str) -> float | None:
        value = self._value(name)
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @property
    def current_temperature(self) -> float | None:
        return self._number("currentTemperature")

    @property
    def target_temperature(self) -> float | None:
        # TargetTemp is the effective target in either manual or schedule mode.
        # PointValue (the write binding) is only the manual target.
        return self._number("targetTemperature")

    @property
    def supported_features(self) -> ClimateEntityFeature:
        # HA's thermostat controls are editable whenever TARGET_TEMPERATURE is
        # advertised, even in AUTO. Advertise it only for the manual setpoint.
        features = self._attr_supported_features
        if self._number("mode") == 0:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        return features

    @property
    def min_temp(self) -> float:
        value = self._number("minTemperature")
        return value if value is not None else super().min_temp

    @property
    def max_temp(self) -> float:
        value = self._number("maxTemperature")
        return value if value is not None else super().max_temp

    @property
    def hvac_mode(self) -> HVACMode | None:
        value = self._number("state")
        if value == 0:
            return HVACMode.OFF
        if value == 1:
            mode = self._number("mode")
            if mode == 2:
                return HVACMode.AUTO
            if mode == 0:
                if self._direction() == 0:
                    return HVACMode.HEAT
                if self._direction() == 1 and self.cooling_enabled:
                    return HVACMode.COOL
        return None

    @property
    def hvac_action(self) -> HVACAction | None:
        state = self._number("state")
        if state == 0:
            return HVACAction.OFF
        if state != 1:
            return None
        output = self._number("controlOutValue")
        if output == 1:
            direction = self._direction()
            if direction == 0:
                return HVACAction.HEATING
            if direction == 1:
                return HVACAction.COOLING
        if output == 0:
            return HVACAction.IDLE
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Preserve effective scheduled targets when editing is not advertised.
        attributes = {
            "grenton_mode": self._value("mode"),
            "schedule_status": self.schedule_status,
            "control_direction": self._value("controlDirection"),
            "control_direction_name": self.control_direction_name,
        }
        if self._number("mode") == 2:
            attributes["scheduled_target_temperature_celsius"] = self.target_temperature
        if schedule := self.decoded_schedule:
            attributes["weekly_schedule"] = schedule.periods()
        return attributes

    async def _execute(self, action_name: str, value: str) -> None:
        # Never change the imported template, including during concurrent calls.
        if action_name not in self.actions:
            raise ServiceValidationError("The thermostat action is not configured")
        await self.coordinator.execute_action(
            replace(self.actions[action_name], value=value), raise_on_error=True
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self.hvac_modes:
            raise ServiceValidationError(f"Unsupported HVAC mode: {hvac_mode}")
        async with self._command_lock:
            await self._set_hvac_mode(hvac_mode)
            await self._refresh_target()

    async def _set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Change mode and power while the caller holds the command lock."""
        if hvac_mode != HVACMode.OFF:
            if hvac_mode in (HVACMode.HEAT, HVACMode.COOL) and (
                "setControlDirectionAction" in self.actions
            ):
                await self._execute(
                    "setControlDirectionAction",
                    "1" if hvac_mode == HVACMode.COOL else "0",
                )
            await self._execute("setModeAction", str(MODE_VALUES[hvac_mode]))
        await self._execute("setStateAction", "0" if hvac_mode == HVACMode.OFF else "1")

    async def async_turn_on(self) -> None:
        # Start in the existing mode; selecting Heat explicitly selects manual.
        async with self._command_lock:
            await self._execute("setStateAction", "1")

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the manual target; schedule operation must be left explicitly."""
        requested_mode = kwargs.get(ATTR_HVAC_MODE)
        if requested_mode is not None and requested_mode not in self.hvac_modes:
            raise ServiceValidationError(f"Unsupported HVAC mode: {requested_mode}")
        value = kwargs.get(ATTR_TEMPERATURE)
        if value is None:
            if requested_mode is not None:
                await self.async_set_hvac_mode(requested_mode)
            return
        try:
            temperature = float(value)
        except (ValueError, TypeError) as error:
            raise ServiceValidationError(
                "Target temperature must be a number"
            ) from error
        if (
            isinstance(value, bool)
            or not math.isfinite(temperature)
            or not self.min_temp <= temperature <= self.max_temp
        ):
            raise ServiceValidationError(
                f"Target temperature must be between {self.min_temp} and {self.max_temp} °C"
            )
        if not math.isclose(temperature * 2, round(temperature * 2), abs_tol=1e-6):
            raise ServiceValidationError(
                "Target temperature must use 0.5 °C increments"
            )
        temperature = round(temperature * 2) / 2
        async with self._command_lock:
            if requested_mode == HVACMode.AUTO or self._number("mode") != 0:
                raise ServiceValidationError(
                    "Select Heat or Cool (manual mode) before changing the target temperature"
                )
            # Updating a target never leaves schedule mode implicitly.
            await self._execute("setTargetTemperatureAction", str(temperature))
            if requested_mode is not None:
                await self._set_hvac_mode(requested_mode)
            await self._refresh_target()

    async def _refresh_target(self) -> None:
        """Read the authoritative target after a write instead of waiting a minute."""
        state = self.states.get("targetTemperature")
        if state is not None:
            await self.coordinator.async_refresh_clu_state(
                state.clu_id, required_states=[state]
            )

    async def async_set_thermostat_schedule(self, schedule: Any) -> None:
        """Replace the complete week without changing mode, power or metadata."""
        async with self._command_lock:
            await self._set_schedule(schedule)

    async def _refresh_schedule(self) -> bool:
        states = [
            self.states[name]
            for name in (
                "scheduleData",
                "minTemperature",
                "maxTemperature",
                "targetTemperature",
            )
        ]
        # Bindings may refer to different CLUs; each required source must reply.
        results = []
        for clu_id in dict.fromkeys(state.clu_id for state in states):
            results.append(
                await self.coordinator.async_refresh_clu_state(
                    clu_id,
                    required_states=[
                        state for state in states if state.clu_id == clu_id
                    ],
                )
            )
        return all(results)

    async def _set_schedule(self, schedule: Any) -> None:
        if schedule is None:
            raise ServiceValidationError("Provide a complete weekly schedule")
        await self._set_schedule_and_limits(schedule)

    async def _set_schedule_and_limits(
        self, schedule: Any = None, limits: Any = None
    ) -> None:
        """Validate everything, write under the command lock, then verify CLU data."""
        if not await self._refresh_schedule():
            raise HomeAssistantError(
                "Could not read the current thermostat schedule and limits from the CLU"
            )
        data = self._value("scheduleData")
        minimum, maximum = (
            self._number("minTemperature"),
            self._number("maxTemperature"),
        )
        if not isinstance(data, str) or not data or minimum is None or maximum is None:
            raise ServiceValidationError(
                "The thermostat schedule and limits have not been received yet"
            )
        try:
            existing = decode_schedule(data, maximum)
            new_minimum, new_maximum = minimum, maximum
            if limits is not None:
                if not isinstance(limits, dict) or set(limits) != {
                    "minimum",
                    "maximum",
                }:
                    raise ValueError("Provide both minimum and maximum temperature")
                new_minimum, new_maximum = limits["minimum"], limits["maximum"]
                validate_limits(new_minimum, new_maximum)
                if (
                    self._number("mode") == 0
                    and (target := self.target_temperature) is not None
                    and not new_minimum <= target <= new_maximum
                ):
                    raise ValueError(
                        "The manual target is outside the proposed limits; change the target first"
                    )
            payload = encode_schedule(
                existing.periods() if schedule is None else schedule,
                data,
                new_minimum,
                new_maximum,
                existing_maximum=maximum,
            )
        except (TypeError, ValueError) as error:
            raise ServiceValidationError(str(error)) from error
        commands: list[tuple[str, str]] = []
        bounds = [
            ("setMinTemperatureAction", new_minimum, minimum),
            ("setMaxTemperatureAction", new_maximum, maximum),
        ]
        if new_minimum >= maximum:
            bounds.reverse()
        commands.extend(
            (name, str(value)) for name, value, old in bounds if value != old
        )
        if schedule is not None or new_maximum != maximum:
            commands.append(("setScheduleDataAction", payload))
        if any(name not in self.actions for name, _ in commands):
            raise ServiceValidationError("The thermostat action is not configured")
        if not commands:
            return
        try:
            for name, value in commands:
                await self._execute(name, value)
        except HomeAssistantError:
            # A timeout may happen after the CLU applied a write. Reconcile it.
            await self._refresh_schedule()
            raise
        expected = decode_schedule(payload, new_maximum)
        fresh = await self._refresh_schedule()
        actual = self.decoded_schedule
        if (
            fresh
            and self._number("minTemperature") == new_minimum
            and self._number("maxTemperature") == new_maximum
            and actual is not None
            and actual.temperatures == expected.temperatures
        ):
            return
        _LOGGER.warning(
            "[%s] CLU did not confirm thermostat schedule/limit changes",
            self._log_context("scheduleData", "minTemperature", "maxTemperature"),
        )
        raise HomeAssistantError(
            "The CLU did not confirm the saved schedule and temperature limits. Reopen configuration to inspect the current device values."
        )
