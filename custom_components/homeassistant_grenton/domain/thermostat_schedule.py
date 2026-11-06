"""Weekly thermostat data inferred from captured myGrenton schedules.

Each Sunday-first 15-minute slot is a two-digit base-90 value scaled from zero
to the maximum temperature (attribute 11), and clamped to 8099 at the maximum.
Object Manager captures include arbitrary codes; display them at the mobile
app's half-degree precision and keep unchanged wire codes verbatim.
The configured minimum (attribute 10) constrains writes without shifting the
encoding. The final pair approximates 8100 / maximum; the preceding four trailer
characters have unknown semantics. Preserve them when changing the range.
"""

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

DAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
SLOTS_PER_DAY = 96
WEEK_LENGTH = 7 * SLOTS_PER_DAY * 2
# Alphabet inferred from the sample values and their numeric ordering.
ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ !#$()*+,-./:;<=>?@[]^_`{|}~"
BASE = len(ALPHABET)
SCALE = BASE * BASE


def _validate_maximum(maximum: float) -> None:
    if isinstance(maximum, bool) or not isinstance(maximum, (int, float)):
        raise TypeError("Maximum temperature must be a number")
    if not math.isfinite(maximum) or maximum <= 0:
        raise ValueError("Maximum temperature must be finite and greater than zero")


def encode_temperature(temperature: Any, maximum: float) -> str:
    """Encode a nonnegative half-degree value using the configured maximum."""
    _validate_maximum(maximum)
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise TypeError("Schedule temperatures must be numbers")
    if not math.isfinite(temperature) or not 0 <= temperature <= maximum:
        raise ValueError(f"Schedule temperatures must be between 0 and {maximum} °C")
    if not math.isclose(temperature * 2, round(temperature * 2), abs_tol=1e-6):
        raise ValueError("Schedule temperatures must use 0.5 °C increments")
    # Captures with a maximum of 33 demonstrate rounding to the nearest code.
    value = min(math.floor(temperature / maximum * SCALE + 0.5), SCALE - 1)
    return ALPHABET[value // BASE] + ALPHABET[value % BASE]


def decode_temperature(pair: str, maximum: float) -> float:
    """Display any valid base-90 code at the mobile app's half-degree precision."""
    _validate_maximum(maximum)
    if len(pair) != 2 or any(char not in ALPHABET for char in pair):
        raise ValueError(f"Invalid encoded schedule temperature: pair {pair!r}")
    value = ALPHABET.index(pair[0]) * BASE + ALPHABET.index(pair[1])
    return math.floor(value / SCALE * maximum * 2 + 0.5) / 2


@dataclass(frozen=True)
class ScheduledPeriod:
    """Scheduled target now and the next actual temperature change."""

    temperature: float
    next_change: datetime | None = None
    next_temperature: float | None = None


@dataclass(frozen=True)
class ThermostatSchedule:
    temperatures: tuple[float, ...]
    trailer: str

    def active_period(self, now: datetime) -> ScheduledPeriod:
        """Walk real quarter-hours so skipped/repeated DST hours stay correct."""
        if now.tzinfo is None:
            raise ValueError("Schedule time must include a time zone")

        def value(at: datetime) -> float:
            slot = ((at.weekday() + 1) % 7) * 96 + at.hour * 4 + at.minute // 15
            return self.temperatures[slot]

        current = value(now)
        if all(temperature == current for temperature in self.temperatures):
            return ScheduledPeriod(current)
        utc_now = now.astimezone(UTC)
        boundary = utc_now.replace(
            minute=utc_now.minute // 15 * 15, second=0, microsecond=0
        ) + timedelta(minutes=15)
        # A change confined to the skipped spring hour can miss a whole week.
        # Cover two local weeks, including their possible DST offset change.
        for offset in range(15 * 96):
            local = (boundary + timedelta(minutes=15 * offset)).astimezone(now.tzinfo)
            if (temperature := value(local)) != current:
                return ScheduledPeriod(current, local, temperature)
        return ScheduledPeriod(current)

    def periods(self) -> dict[str, list[dict[str, Any]]]:
        """Represent each day as temperature changes starting at midnight."""
        days: dict[str, list[dict[str, Any]]] = {}
        for day_index, day in enumerate(DAYS):
            periods: list[dict[str, Any]] = []
            values = self.temperatures[day_index * 96 : (day_index + 1) * 96]
            for slot, temperature in enumerate(values):
                if slot == 0 or temperature != values[slot - 1]:
                    periods.append(
                        {
                            "time": f"{slot // 4:02}:{slot % 4 * 15:02}",
                            "temperature": temperature,
                        }
                    )
            days[day] = periods
        return days


@lru_cache(maxsize=128)
def decode_schedule(data: str, maximum: float) -> ThermostatSchedule:
    """Validate the captured layout and retain its trailer verbatim."""
    _validate_maximum(maximum)
    if len(data) != WEEK_LENGTH + 6:
        raise ValueError(
            "Schedule must contain 672 two-character values and a six-character trailer"
        )
    # The trailing characters change with configuration but are not range text.
    trailer = data[WEEK_LENGTH:]
    if any(char not in ALPHABET for char in trailer):
        raise ValueError("Invalid schedule trailer")
    scale = ALPHABET.index(trailer[-2]) * BASE + ALPHABET.index(trailer[-1])
    if abs(scale - SCALE / maximum) > 1:
        raise ValueError(
            "Schedule metadata does not match the current maximum temperature; wait for an updated schedule"
        )
    temperatures: list[float] = []
    for slot in range(7 * SLOTS_PER_DAY):
        try:
            temperatures.append(
                decode_temperature(data[slot * 2 : slot * 2 + 2], maximum)
            )
        except ValueError as error:
            day, within_day = divmod(slot, SLOTS_PER_DAY)
            raise ValueError(
                f"{error}; {DAYS[day]} {within_day // 4:02}:{within_day % 4 * 15:02}, "
                f"maximum {maximum:g} °C, trailer {trailer!r}"
            ) from error
    return ThermostatSchedule(tuple(temperatures), trailer)


def encode_schedule(
    schedule: Any,
    existing_data: str,
    minimum: float,
    maximum: float,
    *,
    existing_maximum: float | None = None,
) -> str:
    """Build a week; retain metadata, rescaling its final pair for a new maximum."""
    existing = decode_schedule(
        existing_data, maximum if existing_maximum is None else existing_maximum
    )
    same_maximum = existing_maximum is None or existing_maximum == maximum
    _validate_maximum(maximum)
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)):
        raise TypeError("Minimum temperature must be a number")
    if not math.isfinite(minimum) or minimum >= maximum:
        raise ValueError("Minimum temperature must be finite and below the maximum")
    if not isinstance(schedule, dict) or set(schedule) != set(DAYS):
        raise ValueError("Schedule must contain all seven weekday names in lowercase")
    encoded: list[str] = []
    for day_index, day in enumerate(DAYS):
        periods = schedule[day]
        if not isinstance(periods, list) or not 1 <= len(periods) <= SLOTS_PER_DAY:
            raise ValueError(f"{day} must contain 1–96 temperature periods")
        changes: list[tuple[int, str, float]] = []
        for period in periods:
            if not isinstance(period, dict) or set(period) != {"time", "temperature"}:
                raise ValueError("Each period must contain time and temperature")
            time = period["time"]
            if not isinstance(time, str) or not re.fullmatch(
                r"(?:[01]\d|2[0-3]):(?:00|15|30|45)", time
            ):
                raise ValueError("Period times must use HH:MM on 15-minute boundaries")
            hour, minute = map(int, time.split(":"))
            slot = hour * 4 + minute // 15
            if (not changes and slot != 0) or (changes and slot <= changes[-1][0]):
                raise ValueError(
                    "Each day must start at 00:00 with strictly increasing times"
                )
            temperature = period["temperature"]
            pair = encode_temperature(temperature, maximum)
            if decode_temperature(pair, maximum) != temperature:
                raise ValueError("Temperature cannot be represented at this maximum")
            if temperature < minimum:
                raise ValueError(f"Schedule temperatures must be at least {minimum} °C")
            changes.append((slot, pair, temperature))
        for index, (start, pair, temperature) in enumerate(changes):
            end = changes[index + 1][0] if index + 1 < len(changes) else SLOTS_PER_DAY
            for slot in range(start, end):
                position = day_index * SLOTS_PER_DAY + slot
                # Several raw codes can display as the same target. Retain the
                # actual CLU value when the user has not changed this slot.
                encoded.append(
                    existing_data[position * 2 : position * 2 + 2]
                    if same_maximum and temperature == existing.temperatures[position]
                    else pair
                )
    trailer = existing.trailer
    if existing_maximum is not None and existing_maximum != maximum:
        factor = math.floor(SCALE / maximum + 0.5)
        if not 1 <= factor < SCALE:
            raise ValueError(
                "Maximum temperature cannot be represented in schedule metadata"
            )
        trailer = trailer[:4] + ALPHABET[factor // BASE] + ALPHABET[factor % BASE]
    payload = "".join(encoded) + trailer
    # Reject ranges too wide to represent the requested half-degree targets.
    decode_schedule(payload, maximum)
    return payload
