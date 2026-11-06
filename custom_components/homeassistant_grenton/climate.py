"""Set up Grenton climate entities."""

from homeassistant.components.climate import ClimateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .integration_config import GrentonConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: GrentonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add climate entities discovered in the mobile interface."""
    async_add_entities(
        entity
        for device in config_entry.runtime_data.devices
        for entity in device.entities
        if isinstance(entity, ClimateEntity)
    )
