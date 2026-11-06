"""Dynamic thermostat settings and day-grouped weekly schedule selector."""

import math
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.helpers import selector

from ..thermostat_schedule import DAYS, encode_temperature
from .configurable import (
    BaseGrentonEntityConfigurationSchema,
    StepDefinition,
    StepResult,
)


def validate_limits(minimum: Any, maximum: Any) -> None:
    """Require ordered, nonnegative half-degree limits supported by the codec."""
    for value in (minimum, maximum):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("Temperature limits must be numbers")
        if not math.isfinite(value) or value < 0 or value * 2 != round(value * 2):
            raise ValueError("Temperature limits must be nonnegative 0.5 °C increments")
    if minimum >= maximum or maximum <= 1:
        raise ValueError("Minimum must be below maximum, and maximum must exceed 1 °C")


def schedule_sections(
    schedule: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Group days that share identical periods, without losing any changes."""
    sections: list[dict[str, Any]] = []
    for day in (*DAYS[1:], DAYS[0]):
        periods = schedule[day]
        existing = next((item for item in sections if item["periods"] == periods), None)
        if existing is not None:
            existing["days"].append(day)
        else:
            sections.append({"days": [day], "periods": deepcopy(periods)})
    return sections


def sections_schedule(sections: Any) -> dict[str, list[dict[str, Any]]]:
    """Require a complete, unambiguous week before any CLU write."""
    if not isinstance(sections, list) or not 1 <= len(sections) <= 7:
        raise vol.Invalid("Use one to seven schedule sections")
    schedule: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        if not isinstance(section, dict) or set(section) != {"days", "periods"}:
            raise vol.Invalid("Each section needs days and periods")
        days = section["days"]
        if not isinstance(days, list) or not days:
            raise vol.Invalid("Select at least one day per section")
        for day in days:
            if not isinstance(day, str) or day not in DAYS or day in schedule:
                raise vol.Invalid("Each weekday must belong to exactly one section")
            schedule[day] = deepcopy(section["periods"])
    if set(schedule) != set(DAYS):
        raise vol.Invalid("Include all seven weekdays")
    return schedule


@selector.SELECTORS.register("grenton_thermostat")
class GrentonThermostatSelector(selector.Selector):
    """Settings with repeatable sections and repeatable quarter-hour periods."""

    selector_type = "grenton_thermostat"
    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Required("cooling_available"): bool,
            vol.Required("schedule_available"): bool,
            vol.Optional("limits_available", default=False): bool,
            vol.Optional("minimum"): vol.Coerce(float),
            vol.Optional("maximum"): vol.Coerce(float),
            vol.Optional("direction"): vol.In(["heating", "cooling"]),
        }
    )

    def __call__(self, data: Any) -> dict[str, Any]:
        # HA's flow manager validates before our generic step handler does.
        # Keep the editor draft intact across both passes; normalize only in
        # the step's post-validation hook, immediately before applying it.
        self.configuration(data)
        return deepcopy(data)

    def configuration(self, data: Any) -> dict[str, Any]:
        """Validate the editor draft and build the commands to apply."""
        if not isinstance(data, dict):
            raise vol.Invalid("Thermostat settings must be an object")
        cooling = data.get("cooling_enabled")
        if not isinstance(cooling, bool) or (
            cooling and not self.config["cooling_available"]
        ):
            raise vol.Invalid("Cooling needs readable and writable direction bindings")
        edit = data.get("edit_schedule", False)
        if not isinstance(edit, bool):
            raise vol.Invalid("Schedule editing must be enabled or disabled")
        result: dict[str, Any] = {"cooling_enabled": cooling}
        if "schedule_polling_enabled" in data:
            polling = data["schedule_polling_enabled"]
            if not isinstance(polling, bool):
                raise vol.Invalid(
                    "Schedule synchronization must be enabled or disabled"
                )
            result["schedule_polling_enabled"] = polling
        direction = data.get("control_direction", "unchanged")
        if direction not in ("unchanged", "heating", "cooling"):
            raise vol.Invalid("Choose heating, cooling, or keep the current direction")
        if cooling and direction != "unchanged":
            result["control_direction"] = direction
        minimum, maximum = self.config.get("minimum"), self.config.get("maximum")
        edit_limits = data.get("edit_limits", False)
        if not isinstance(edit_limits, bool):
            raise vol.Invalid("Limit editing must be enabled or disabled")
        if edit_limits:
            if not self.config["limits_available"]:
                raise vol.Invalid(
                    "Wait for the current schedule and limits from the CLU"
                )
            minimum, maximum = data.get("minimum"), data.get("maximum")
            try:
                validate_limits(minimum, maximum)
            except (TypeError, ValueError) as err:
                raise vol.Invalid(str(err)) from err
            result["limits"] = {"minimum": minimum, "maximum": maximum}
        if edit:
            if not self.config["schedule_available"]:
                raise vol.Invalid(
                    "Wait for the current schedule and limits from the CLU"
                )
            result["schedule"] = sections_schedule(data.get("sections"))
            for periods in result["schedule"].values():
                if not isinstance(periods, list) or not 1 <= len(periods) <= 96:
                    raise vol.Invalid("Use one to 96 periods per section")
                if all(
                    isinstance(period, dict) and isinstance(period.get("time"), str)
                    for period in periods
                ):
                    periods.sort(key=lambda period: period["time"])
                previous = ""
                for index, period in enumerate(periods):
                    if not isinstance(period, dict) or set(period) != {
                        "time",
                        "temperature",
                    }:
                        raise vol.Invalid(
                            "Each period needs a start time and temperature"
                        )
                    time = period["time"]
                    if (
                        not isinstance(time, str)
                        or not re.fullmatch(r"(?:[01]\d|2[0-3]):(?:00|15|30|45)", time)
                        or (index == 0 and time != "00:00")
                        or time <= previous
                    ):
                        raise vol.Invalid(
                            "Start at 00:00 with increasing quarter-hour times"
                        )
                    try:
                        encode_temperature(period["temperature"], maximum)
                        if period["temperature"] < minimum:
                            raise ValueError(
                                "Temperature is below the configured minimum"
                            )
                    except (TypeError, ValueError) as err:
                        raise vol.Invalid(str(err)) from err
                    previous = time
        return result


@dataclass
class GrentonThermostatConfigurationSchema(BaseGrentonEntityConfigurationSchema):
    settings: dict[str, Any]
    sections: list[dict[str, Any]]

    @property
    def steps(self) -> list[StepDefinition]:
        return [StepDefinition("configure_thermostat", self._build)]

    def _build(
        self, current: dict[str, Any], accumulated: dict[str, Any]
    ) -> StepResult:
        draft = deepcopy(
            current.get(
                "thermostat",
                {
                    "cooling_enabled": current.get("cooling_enabled", False),
                    "schedule_polling_enabled": current.get(
                        "schedule_polling_enabled", True
                    ),
                    "edit_schedule": False,
                    "edit_limits": False,
                    "minimum": self.settings.get("minimum"),
                    "maximum": self.settings.get("maximum"),
                    "control_direction": "unchanged",
                    "sections": self.sections,
                },
            )
        )
        editor = GrentonThermostatSelector(self.settings)
        return StepResult(
            schema=vol.Schema(
                {
                    vol.Required(
                        "thermostat", description={"suggested_value": draft}
                    ): editor
                }
            ),
            validator=lambda data: editor.configuration(data["thermostat"]),
        )
