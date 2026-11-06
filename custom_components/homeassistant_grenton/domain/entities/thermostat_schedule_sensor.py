"""Read-only weekly thermostat schedule on the native HA device page."""

from datetime import datetime
from typing import Any, cast

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from ..thermostat_schedule import DAYS
from .base import BaseGrentonEntity
from .thermostat_v2 import GrentonEntityThermostatV2


class GrentonThermostatScheduleSensor(BaseGrentonEntity, SensorEntity):
    """Display the CLU's saved schedule even while manual mode is selected."""

    _attr_translation_key = "thermostat_schedule"
    _attr_icon = "mdi:calendar-clock"
    _unrecorded_attributes = frozenset(DAYS)

    def __init__(self, thermostat: GrentonEntityThermostatV2, id: str) -> None:
        # The shared widget label keeps the device's existing name unchanged.
        super().__init__(
            thermostat.coordinator,
            id,
            thermostat.label,
            cast(DeviceInfo | None, thermostat.device_info),
        )
        self.thermostat = thermostat

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._refresh_time, minute=[0, 15, 30, 45], second=0
            )
        )

    @callback
    def _refresh_time(self, now: datetime) -> None:
        self.async_write_ha_state()

    def _now(self) -> datetime:
        zone = dt_util.get_time_zone(self.hass.config.time_zone) if self.hass else None
        return dt_util.now(zone)

    def _temperature(self, value: float) -> str:
        unit = (
            self.hass.config.units.temperature_unit
            if self.hass
            else UnitOfTemperature.CELSIUS
        )
        converted = TemperatureConverter.convert(value, UnitOfTemperature.CELSIUS, unit)
        return f"{round(converted, 1):g}{unit}"

    @property
    def native_value(self) -> str | None:
        if (schedule := self.thermostat.decoded_schedule) is None:
            return None
        now = self._now()
        period = schedule.active_period(now)
        temperature = self._temperature(period.temperature)
        polish = self.hass is not None and self.hass.config.language.startswith("pl")
        if period.next_change is None:
            return f"{temperature} {'cały tydzień' if polish else 'all week'}"
        change = period.next_change
        clock = change.strftime("%H:%M")
        if change.date() != now.date():
            days = (
                ("pon", "wt", "śr", "czw", "pt", "sob", "nd")
                if polish
                else ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
            )
            clock = f"{days[change.weekday()]} {clock}"
        return f"{temperature} {'do' if polish else 'until'} {clock}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes: dict[str, Any] = {
            "following_schedule": self.thermostat.following_schedule,
            "direction": self.thermostat.control_direction_name,
        }
        if (schedule := self.thermostat.decoded_schedule) is None:
            return attributes
        period = schedule.active_period(self._now())
        attributes.update(
            scheduled_target=self._temperature(period.temperature),
            next_change=period.next_change.isoformat() if period.next_change else None,
            next_target=self._temperature(period.next_temperature)
            if period.next_temperature is not None
            else None,
        )
        days = schedule.periods()
        for day in (*DAYS[1:], DAYS[0]):
            periods = days[day]
            attributes[day] = " · ".join(
                f"{item['time']}–{periods[index + 1]['time'] if index + 1 < len(periods) else '24:00'}: "
                f"{self._temperature(item['temperature'])}"
                for index, item in enumerate(periods)
            )
        return attributes
