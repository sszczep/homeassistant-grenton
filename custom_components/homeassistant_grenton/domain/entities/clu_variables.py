"""User-selected CLU variables, exposed as sensors or boolean switches."""

from dataclasses import dataclass, field
from math import isfinite
from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_UNIT_OF_MEASUREMENT
from homeassistant.helpers import selector

from ...coordinator import GrentonCoordinator
from ..action import GrentonActionVariable
from ..clu import GrentonClu
from ..enums import GrentonActionEventType, GrentonValueType
from ..state_object import GrentonVariableValueObject
from .base import BaseGrentonEntity
from .clu import clu_device_info
from .configurable import ConfigurableEntity, StepDefinition, StepResult
from .value import (
    TEMPORAL_DEVICE_CLASSES,
    GrentonEntityValue,
    GrentonEntityValueConfigurationSchema,
    normalize_sensor_config,
)

CLU_VARIABLES = "clu_variables"


def variable_definitions(options: dict, clu_id: str) -> dict[str, dict[str, Any]]:
    """Keep custom variable configuration scoped to its owning CLU."""
    return options.get(CLU_VARIABLES, {}).get(clu_id, {})


def variable_options(
    options: dict, clu_id: str, variable_id: str, config: dict | None
) -> dict:
    """Replace or remove one definition while preserving every other option."""
    result = dict(options)
    clus = dict(result.get(CLU_VARIABLES, {}))
    variables = dict(clus.get(clu_id, {}))
    if config is None:
        variables.pop(variable_id, None)
    else:
        variables[variable_id] = config
    clus[clu_id] = variables
    result[CLU_VARIABLES] = clus
    return result


def normalize_variable(config: dict[str, Any]) -> dict[str, Any]:
    """Discard sensor settings when the selected type does not use them."""
    result = normalize_sensor_config(config)
    result["variable_name"] = result["variable_name"].strip()
    result["label"] = result.get("label", "").strip() or result["variable_name"]
    result.setdefault("read_mode", "realtime")
    if result["grenton_type"] == GrentonValueType.BOOLEAN:
        result.pop("device_class", None)
        result.pop(CONF_UNIT_OF_MEASUREMENT, None)
    return result


@dataclass
class CluVariableConfigurationSchema(GrentonEntityValueConfigurationSchema):
    """Define the variable first, then use the existing VALUE_V2 sensor steps."""

    variables: dict[str, dict[str, Any]] = field(default_factory=dict)
    variable_id: str = ""

    @property
    def steps(self) -> list[StepDefinition]:
        return [
            StepDefinition("configure_clu_variable", self._variable_step),
            *super().steps,
        ]

    def _variable_step(self, current: dict, accumulated: dict) -> StepResult:
        def validate(data):
            name = data["variable_name"].strip()
            if not name or any(
                key != self.variable_id and config["variable_name"] == name
                for key, config in self.variables.items()
            ):
                raise vol.Invalid("Empty or duplicate variable", path=["variable_name"])
            return {**data, "variable_name": name}

        return StepResult(
            schema=vol.Schema(
                {
                    vol.Required(
                        "variable_name", default=current.get("variable_name", "")
                    ): selector.TextSelector(),
                    vol.Optional(
                        "label", default=current.get("label", "")
                    ): selector.TextSelector(),
                    vol.Required(
                        "grenton_type", default=current.get("grenton_type", "STRING")
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[value.value for value in GrentonValueType],
                            translation_key="grenton_variable_types",
                        )
                    ),
                    vol.Required(
                        "read_mode", default=current.get("read_mode", "realtime")
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["realtime", "slow"],
                            translation_key="value_read_modes",
                        )
                    ),
                }
            ),
            validator=validate,
        )

    def _build_step_class_schema(self, current: dict, accumulated: dict) -> StepResult:
        if accumulated.get("grenton_type") == GrentonValueType.BOOLEAN:
            return StepResult(schema=vol.Schema({}), complete=True)
        return StepResult(
            schema=vol.Schema(
                {
                    vol.Required(
                        "device_class", default=current.get("device_class", "none")
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["none", *[dc.value for dc in SensorDeviceClass]],
                            translation_key="sensor_device_classes",
                            sort=True,
                        )
                    ),
                }
            )
        )


class CluVariableConfiguration(ConfigurableEntity[CluVariableConfigurationSchema]):
    """Persist custom variables separately from imported widget configurations."""

    reload_after_configuration = True

    def _register_state(self, state):
        self.coordinator.register_component_state(
            state, read_mode=self._config.get("read_mode", "realtime")
        )

    @property
    def available(self):
        return super().available and self.coordinator.is_state_fresh(self.state_object)

    def _get_schema_instance(self):
        return CluVariableConfigurationSchema(
            variables=variable_definitions(
                self.coordinator.config_entry.options, self.clu.id
            ),
            variable_id=self.variable_id,
        )

    def _load_config(self, defaults):
        return dict(
            variable_definitions(self.coordinator.config_entry.options, self.clu.id)[
                self.variable_id
            ]
        )

    async def apply_configuration(self, user_input):
        self._config = normalize_variable(user_input)
        return variable_options(
            self.coordinator.config_entry.options,
            self.clu.id,
            self.variable_id,
            self._config,
        )


class GrentonCluVariableSensor(CluVariableConfiguration, GrentonEntityValue):
    """VALUE_V2 sensor behavior for a user-selected CLU variable."""

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        clu: GrentonClu,
        variable_id: str,
        config: dict,
    ) -> None:
        self.clu = clu
        self.variable_id = variable_id
        GrentonEntityValue.__init__(
            self,
            coordinator=coordinator,
            id=f"clu_{clu.id}_variable_{variable_id}",
            label=config["label"],
            state_object=GrentonVariableValueObject(
                clu.id, "", config["variable_name"]
            ),
            value_type=GrentonValueType(config["grenton_type"]),
            device_info=clu_device_info(clu),
        )
        self._attr_extra_state_attributes = {
            "grenton_type": config["grenton_type"],
        }

    @property
    def native_value(self):
        # A variable may not exist yet or its initial subscription may fail.
        # HA numeric sensors require None, rather than an empty/invalid string.
        try:
            value = super().native_value
        except (ValueError, TypeError, OverflowError):
            return None
        if (
            self.device_class in TEMPORAL_DEVICE_CLASSES
            or self.value_type == GrentonValueType.STRING
        ):
            return value
        if not isinstance(value, (int, float)) or not isfinite(value):
            return None
        return value


class GrentonCluVariableSwitch(
    CluVariableConfiguration, BaseGrentonEntity, SwitchEntity
):
    """Write a real boolean to a CLU variable and read its state back."""

    def __init__(
        self,
        coordinator: GrentonCoordinator,
        clu: GrentonClu,
        variable_id: str,
        config: dict,
    ) -> None:
        self.clu = clu
        self.variable_id = variable_id
        BaseGrentonEntity.__init__(
            self,
            coordinator,
            f"clu_{clu.id}_variable_{variable_id}",
            config["label"],
            clu_device_info(clu),
        )
        CluVariableConfiguration.__init__(self)
        self.state_object = GrentonVariableValueObject(
            clu.id, "", config["variable_name"]
        )
        self._attr_extra_state_attributes = {
            "grenton_type": config["grenton_type"],
        }
        self._register_state(self.state_object)

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.get_value_for_component(self.state_object)
        if isinstance(value, str):
            value = value.strip().lower()
            if value in ("true", "1"):
                return True
            if value in ("false", "0"):
                return False
        if isinstance(value, bool) or value in (0, 1):
            return bool(value)
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_enabled(False)

    async def _set_enabled(self, enabled: bool) -> None:
        literal = "true" if enabled else "false"
        await self.coordinator.execute_action(
            GrentonActionVariable(
                clu_id=self.clu.id,
                object_name="",
                index=self.state_object.index,
                event=GrentonActionEventType.ON
                if enabled
                else GrentonActionEventType.OFF,
                value=literal,
                lua_value=literal,
            ),
            raise_on_error=True,
        )
        await self.coordinator.async_refresh_clu_state(self.clu.id)


def custom_variable_entities(coordinator: GrentonCoordinator, clu: GrentonClu):
    """Expose only variables explicitly selected for this CLU."""
    return [
        (
            GrentonCluVariableSwitch
            if config["grenton_type"] == GrentonValueType.BOOLEAN
            else GrentonCluVariableSensor
        )(coordinator, clu, variable_id, config)
        for variable_id, config in variable_definitions(
            coordinator.config_entry.options, clu.id
        ).items()
    ]


GrentonCluCustomVariable = GrentonCluVariableSensor | GrentonCluVariableSwitch
