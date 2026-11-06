"""Bindings supplied by a THERMOSTAT_V2 widget."""

from pydantic import AliasChoices, BaseModel, Field

from ..action import GrentonActionUnionDto
from ..value import GrentonValueUnionDto


class GrentonObjectThermostatV2Dto(BaseModel):
    controlDirection: GrentonValueUnionDto | None = None
    setControlDirectionAction: GrentonActionUnionDto | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "setControlDirectionAction", "setControlDirection"
        ),
    )
    state: GrentonValueUnionDto
    setStateAction: GrentonActionUnionDto
    mode: GrentonValueUnionDto
    setModeAction: GrentonActionUnionDto
    currentTemperature: GrentonValueUnionDto
    targetTemperature: GrentonValueUnionDto
    setTargetTemperatureAction: GrentonActionUnionDto
    minTemperature: GrentonValueUnionDto
    setMinTemperatureAction: GrentonActionUnionDto
    maxTemperature: GrentonValueUnionDto
    setMaxTemperatureAction: GrentonActionUnionDto
    controlOutValue: GrentonValueUnionDto
    scheduleData: GrentonValueUnionDto
    setScheduleDataAction: GrentonActionUnionDto
