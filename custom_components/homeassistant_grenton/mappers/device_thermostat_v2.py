"""Map a thermostat widget to its climate entity."""

from ..coordinator import GrentonCoordinator
from ..domain.action import GrentonAction, GrentonActionAttribute
from ..domain.devices.thermostat_v2 import GrentonDeviceThermostatV2
from ..domain.entities.thermostat_limit_sensor import GrentonThermostatLimitSensor
from ..domain.entities.thermostat_schedule_sensor import GrentonThermostatScheduleSensor
from ..domain.entities.thermostat_v2 import GrentonEntityThermostatV2
from ..domain.enums import GrentonActionEventType
from ..domain.state_object import GrentonAttributeValueObject, GrentonStateObject
from ..dto.widgets.thermostat_v2 import GrentonWidgetThermostatV2Dto


class DeviceThermostatV2Mapper:
    @staticmethod
    def to_domain(
        dto: GrentonWidgetThermostatV2Dto, coordinator: GrentonCoordinator
    ) -> GrentonDeviceThermostatV2:
        device = GrentonDeviceThermostatV2(type=dto.type, id=dto.id, entities=[])
        bindings = dto.object
        states = {
            name: GrentonStateObject.from_dto(getattr(bindings, name))
            for name in (
                "state",
                "mode",
                "currentTemperature",
                "targetTemperature",
                "minTemperature",
                "maxTemperature",
                "controlOutValue",
                "scheduleData",
            )
        }
        actions = {
            name: GrentonAction.from_dto(getattr(bindings, name))
            for name in (
                "setStateAction",
                "setModeAction",
                "setTargetTemperatureAction",
                "setScheduleDataAction",
                "setMinTemperatureAction",
                "setMaxTemperatureAction",
            )
        }
        cooling_detected = (
            bindings.controlDirection is not None
            and bindings.setControlDirectionAction is not None
        )
        # Direction is a built-in thermostat attribute even when omitted by OM.
        # Derive its target only from an attribute on the thermostat itself.
        anchor = next(
            (
                states[name]
                for name in ("mode", "state", "targetTemperature")
                if isinstance(states[name], GrentonAttributeValueObject)
            ),
            None,
        )
        if bindings.controlDirection is not None:
            states["controlDirection"] = GrentonStateObject.from_dto(
                bindings.controlDirection
            )
        elif anchor is not None:
            states["controlDirection"] = GrentonAttributeValueObject(
                clu_id=anchor.clu_id, object_name=anchor.object_name, index="7"
            )
        if bindings.setControlDirectionAction is not None:
            actions["setControlDirectionAction"] = GrentonAction.from_dto(
                bindings.setControlDirectionAction
            )
        elif anchor is not None:
            actions["setControlDirectionAction"] = GrentonActionAttribute(
                clu_id=anchor.clu_id,
                object_name=anchor.object_name,
                index="7",
                event=GrentonActionEventType.CLICK,
                value="$value$",
            )
        thermostat = GrentonEntityThermostatV2(
            coordinator=coordinator,
            id=f"{dto.id}_climate",
            label=dto.label,
            states=states,
            actions=actions,
            device_info=device.device_info,
            cooling_detected=cooling_detected,
        )
        device.entities = [
            thermostat,
            GrentonThermostatScheduleSensor(thermostat, f"{dto.id}_schedule"),
            GrentonThermostatLimitSensor(thermostat, f"{dto.id}_min_temperature", True),
            GrentonThermostatLimitSensor(
                thermostat, f"{dto.id}_max_temperature", False
            ),
        ]
        return device
