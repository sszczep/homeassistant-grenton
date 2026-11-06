"""Persisted slow-read policy shared by entity options and the coordinator."""

import math
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

CONF_SLOW_READ_INTERVAL = "slow_read_interval"
CONF_CLU_READ_SETTINGS = "clu_read_settings"
DEFAULT_SLOW_READ_INTERVAL = 60
MIN_SLOW_READ_INTERVAL = 1
MAX_SLOW_READ_INTERVAL = 86400


def validate_slow_read_interval(value: Any) -> int:
    """Accept whole seconds from the native HA number selector."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not MIN_SLOW_READ_INTERVAL <= value <= MAX_SLOW_READ_INTERVAL
        or not math.isfinite(value)
        or value != int(value)
    ):
        raise vol.Invalid("Use a whole number of seconds between 1 and 86400")
    return int(value)


def slow_read_interval(options: Mapping[str, Any], clu_id: str) -> int:
    """Resolve a CLU's interval, inheriting an earlier global setting if present."""
    settings = options.get(CONF_CLU_READ_SETTINGS, {})
    current = settings.get(clu_id, {}) if isinstance(settings, Mapping) else {}
    value = (
        current.get(CONF_SLOW_READ_INTERVAL) if isinstance(current, Mapping) else None
    )
    if value is None:
        value = options.get(CONF_SLOW_READ_INTERVAL, DEFAULT_SLOW_READ_INTERVAL)
    try:
        return validate_slow_read_interval(value)
    except vol.Invalid:
        return DEFAULT_SLOW_READ_INTERVAL
