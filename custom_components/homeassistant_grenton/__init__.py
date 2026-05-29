import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .integration_config import GrentonConfigEntry, GrentonConfigEntryData, RuntimeData
from .coordinator import GrentonCoordinator
from .mappers.device_mapper import DeviceMapper

from .dto.mobile_interface import GrentonMobileInterfaceDto
from .domain.encryption import GrentonEncryption
from .domain.clu import GrentonClu

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.SENSOR, Platform.LIGHT, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.COVER, Platform.CAMERA]

async def async_setup_entry(hass: HomeAssistant, config_entry: GrentonConfigEntry) -> bool:
    _LOGGER.debug("Initializing Home Assistant Grenton integration")
    
    config_data: GrentonConfigEntryData = config_entry.data # type: ignore

    mobile_interface_dto = GrentonMobileInterfaceDto(**config_data["interface"])
    
    # Create coordinator first (before devices need it)
    encryption = GrentonEncryption.from_dto(mobile_interface_dto.encryption)
    clus = [GrentonClu.from_dto(clu) for clu in mobile_interface_dto.clus]
    coordinator = GrentonCoordinator(hass, config_entry, clus, encryption)
    
    _LOGGER.debug("Loaded interface with %d CLU(s)", len(clus))
    _LOGGER.debug("CLU details:")
    for clu in clus:
        _LOGGER.debug("- CLU %s (%s) at %s:%d", clu.name, clu.serial_number, clu.ip, clu.port)
    
    # Map mobile interface DTO to devices
    devices = DeviceMapper.from_mobile_interface(mobile_interface_dto, coordinator)

    _LOGGER.debug("Mapped %d device(s) from mobile interface", len(devices))
    _LOGGER.debug("Device details:")
    for device in devices:
        _LOGGER.debug("- Device %s (%s) with %d entity(ies)", device.type, device.id, len(device.entities))
        _LOGGER.debug("  Entities:")
        for entity in device.entities:
            _LOGGER.debug("  - Entity %s", entity.name)
    
    # Store runtime data
    config_entry.runtime_data = RuntimeData(coordinator=coordinator, devices=devices)

    # Drop entities and devices that no longer exist in the freshly fetched interface
    _cleanup_orphans(hass, config_entry, devices)

    # Setup the coordinator
    await coordinator.async_setup()

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


def _cleanup_orphans(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    devices: list,
) -> None:
    """Remove entity/device registry entries that no longer back a live widget.

    Why: device_info identifiers and entity unique_ids are derived from widget IDs
    in the mobile interface JSON. After a reconfigure that drops widgets, the old
    registry rows would otherwise linger as `unavailable`.
    """
    valid_entity_uids: set[str] = {
        entity.unique_id
        for device in devices
        for entity in device.entities
        if entity.unique_id
    }
    valid_device_identifiers: set[tuple[str, str]] = {
        ("grenton", device.id) for device in devices
    }

    entity_reg = er.async_get(hass)
    for entry in er.async_entries_for_config_entry(entity_reg, config_entry.entry_id):
        if entry.unique_id not in valid_entity_uids:
            _LOGGER.debug("Removing orphaned entity %s (uid=%s)", entry.entity_id, entry.unique_id)
            entity_reg.async_remove(entry.entity_id)

    device_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_reg, config_entry.entry_id):
        if not any(identifier in valid_device_identifiers for identifier in device.identifiers):
            _LOGGER.debug("Removing orphaned device %s", device.id)
            device_reg.async_update_device(device.id, remove_config_entry_id=config_entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    coordinator: GrentonCoordinator = config_entry.runtime_data.coordinator
    
    # Shutdown coordinator (close UDP sockets)
    await coordinator.async_shutdown()
    
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
    
    return unload_ok