import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.climate import ClimateEntity

from . import GrentonConfigEntry

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: GrentonConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    devices = config_entry.runtime_data.devices

    # Get all climate entities
    entities: list[ClimateEntity] = []
    for device in devices:
        for entity in device.entities:
            if isinstance(entity, (ClimateEntity)):
                entities.append(entity)

    async_add_entities(entities)