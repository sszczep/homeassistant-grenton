"""THERMOSTAT (v1) widget, mapped onto the THERMOSTAT_V2 bindings.

The v1 widget lists one component per role (THERMOSTAT_STATE, _MODE,
_CURRENT_TEMP, _TARGET_TEMP, _OPERATIONAL_STATE, _SCHEDULE, _SCHEDULE_MIN_TEMP,
_SCHEDULE_MAX_TEMP), each with its own state and optional CLICK action. They
address the same THERMOSTAT object features as THERMOSTAT_V2, so the widget is
converted and handled by the V2 thermostat entity (schedule and limits included).
"""
from __future__ import annotations

from typing import Any, List, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import GrentonWidgetDto
from .thermostat_v2 import GrentonWidgetThermostatV2Dto

# component type -> (V2 state binding, V2 action binding or None)
_ROLES: dict[str, tuple[str, str | None]] = {
    "THERMOSTAT_STATE": ("state", "setStateAction"),
    "THERMOSTAT_MODE": ("mode", "setModeAction"),
    "THERMOSTAT_CURRENT_TEMP": ("currentTemperature", None),
    "THERMOSTAT_TARGET_TEMP": ("targetTemperature", "setTargetTemperatureAction"),
    "THERMOSTAT_OPERATIONAL_STATE": ("controlOutValue", None),
    "THERMOSTAT_SCHEDULE": ("scheduleData", "setScheduleDataAction"),
    "THERMOSTAT_SCHEDULE_MIN_TEMP": ("minTemperature", "setMinTemperatureAction"),
    "THERMOSTAT_SCHEDULE_MAX_TEMP": ("maxTemperature", "setMaxTemperatureAction"),
    "THERMOSTAT_CONTROL_DIRECTION": ("controlDirection", "setControlDirectionAction"),
}


class GrentonThermostatComponentDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    label: str | None = None
    image: str | None = None
    state: dict[str, Any] | None = None
    actions: List[dict[str, Any]] = Field(default_factory=list)


class GrentonWidgetThermostatDto(GrentonWidgetDto):
    model_config = ConfigDict(extra="ignore")

    type: Literal["THERMOSTAT"] = "THERMOSTAT"
    label: str | None = None
    components: List[GrentonThermostatComponentDto]

    @model_validator(mode="after")
    def _convertible(self) -> "GrentonWidgetThermostatDto":
        # Fail during parsing (widget skipped with a reason), not later in setup
        self.to_v2()
        return self

    def to_v2(self) -> GrentonWidgetThermostatV2Dto:
        bindings: dict[str, Any] = {}
        label: str | None = (self.label or "").strip() or None
        icon = "temperature"
        for component in self.components:
            role = _ROLES.get(component.type)
            if role is None:
                continue
            state_name, action_name = role
            if component.state is not None:
                bindings[state_name] = component.state
            if action_name is not None:
                click = next((a for a in component.actions if a.get("event", "CLICK") == "CLICK"), None)
                if click is not None:
                    bindings[action_name] = click
            if component.type == "THERMOSTAT_STATE":
                label = label or (component.label or "").strip() or None
                icon = component.image or icon
        # Missing roles raise a validation error, which skips the widget with a reason
        return GrentonWidgetThermostatV2Dto.model_validate({
            "id": self.id,
            "label": label or self.id,
            "icon": icon,
            "object": bindings,
        })
