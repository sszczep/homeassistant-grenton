import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.button import ButtonEntity

from . import GrentonConfigEntry

_LOGGER = logging.getLogger(__name__)

SERVICE_RUN_SCENE = "run_scene"
SERVICE_RUN_SCENE_SCHEMA = {
    vol.Optional("parameter"): cv.string,
}

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: GrentonConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    devices = config_entry.runtime_data.devices

    # Get all button entities
    entities: list[ButtonEntity] = []
    for device in devices:
        for entity in device.entities:
            if isinstance(entity, (ButtonEntity)):
                entities.append(entity)

    async_add_entities(entities)

    # Register entity service for SCENE buttons. Exposed as `grenton.run_scene`.
    # The service only takes effect on entities that implement `run_with_parameter`
    # (i.e. GrentonEntitySceneButton); regular buttons are unaffected.
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_RUN_SCENE,
        SERVICE_RUN_SCENE_SCHEMA,
        "run_with_parameter",
    )
