import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

from .integration_config import GrentonConfigEntry, GrentonConfigEntryData, RuntimeData
from .coordinator import GrentonCoordinator
from .mappers.device_mapper import DeviceMapper

from .dto.mobile_interface import GrentonMobileInterfaceDto
from .domain.encryption import GrentonEncryption
from .domain.clu import GrentonClu

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.SENSOR, Platform.LIGHT]

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

    # Setup the coordinator
    await coordinator.async_setup()
    
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    coordinator: GrentonCoordinator = config_entry.runtime_data.coordinator
    
    # Shutdown coordinator (close UDP sockets)
    await coordinator.async_shutdown()
    
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
    
    return unload_ok