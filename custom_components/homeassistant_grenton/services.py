"""Integration actions targeting CLU controllers and scene buttons."""

import asyncio

import voluptuous as vol
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .domain.entities.clu import GrentonCluEntity
from .domain.entities.scene_button import GrentonEntitySceneButton
from .domain.entities.scene_configuration import scene_arguments_selector
from .domain.entities.thermostat_v2 import GrentonEntityThermostatV2

SERVICE_RUN_SCRIPT = "run_script"
SERVICE_RUN_SCENE = "run_scene"
SERVICE_SET_THERMOSTAT_SCHEDULE = "set_thermostat_schedule"
SERVICE_SET_THERMOSTAT_SCHEDULE_SCHEMA = cv.make_entity_service_schema(
    {vol.Required("schedule"): dict}
)
SERVICE_RUN_SCENE_SCHEMA = {
    vol.Optional("parameter"): cv.string,
}
SERVICE_RUN_SCRIPT_SCHEMA = {
    vol.Required("script"): vol.All(str, str.strip, vol.Length(min=1)),
    vol.Optional("arguments", default=list): scene_arguments_selector(),
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register once, independently of loaded entries and their platforms."""
    service.async_register_batched_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_RUN_SCRIPT,
        entity_domain=Platform.SENSOR,
        schema=SERVICE_RUN_SCRIPT_SCHEMA,
        func=_async_run_script,
    )
    service.async_register_batched_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_RUN_SCENE,
        entity_domain=Platform.BUTTON,
        schema=SERVICE_RUN_SCENE_SCHEMA,
        func=_async_run_scene,
    )
    service.async_register_batched_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_THERMOSTAT_SCHEDULE,
        entity_domain=Platform.CLIMATE,
        schema=SERVICE_SET_THERMOSTAT_SCHEDULE_SCHEMA,
        func=_async_set_thermostat_schedule,
    )


async def _async_set_thermostat_schedule(
    entities: list[Entity], call: ServiceCall
) -> None:
    """Update thermostat schedules using Home Assistant target resolution."""
    thermostats = [
        entity for entity in entities if isinstance(entity, GrentonEntityThermostatV2)
    ]
    if not thermostats:
        raise ServiceValidationError("Select a Grenton thermostat entity or device")
    await asyncio.gather(
        *(
            entity.async_set_thermostat_schedule(call.data["schedule"])
            for entity in thermostats
        )
    )


async def _async_run_scene(entities: list[Entity], call: ServiceCall) -> None:
    """Run selected SCENE buttons with the upstream runtime parameter."""
    await asyncio.gather(
        *(
            entity.run_with_parameter(call.data.get("parameter"))
            for entity in entities
            if isinstance(entity, GrentonEntitySceneButton)
        )
    )


async def _async_run_script(entities: list[Entity], call: ServiceCall) -> None:
    """Select controllers, preserving HA target resolution and permissions."""
    # Device/area targets can include other Grenton sensors. Only controllers
    # can execute scripts; selecting an ordinary sensor alone is an error.
    controllers = [
        entity for entity in entities if isinstance(entity, GrentonCluEntity)
    ]
    if not controllers:
        raise ServiceValidationError("Select a Grenton CLU controller entity or device")
    await asyncio.gather(
        *(
            entity.async_run_script(call.data["script"], call.data["arguments"])
            for entity in controllers
        )
    )
