import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .integration_config import GrentonConfigEntry, GrentonConfigEntryData, RuntimeData
from .coordinator import GrentonCoordinator
from .mappers.device_mapper import DeviceMapper
from .naming import CONF_DEVICE_NAMES, CONF_PAGE_AREAS
from homeassistant.components import webhook
from aiohttp import web

from .gate import (
    CONF_GATE,
    CONF_GATE_URL,
    CONF_GATE_SCAN_INTERVAL,
    CONF_GATE_WEBHOOK_ID,
    DEFAULT_SCAN_INTERVAL,
    GrentonGateCoordinator,
)
from .manual_objects import CONF_MANUAL_OBJECTS, TRANSPORT_GATE, GrentonDeviceManual, build_manual_devices
from .domain.entities.connectivity import GrentonEntityConnectivity

from .dto.mobile_interface import GrentonMobileInterfaceDto
from .domain.encryption import GrentonEncryption
from .domain.clu import GrentonClu

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.SENSOR, Platform.LIGHT, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.COVER, Platform.CAMERA, Platform.CLIMATE]

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
    devices = DeviceMapper.from_mobile_interface(
        mobile_interface_dto,
        coordinator,
        device_names=config_entry.data.get(CONF_DEVICE_NAMES),
        page_areas=config_entry.data.get(CONF_PAGE_AREAS),
    )

    _LOGGER.debug("Mapped %d device(s) from mobile interface", len(devices))

    # Manually added objects (UDP via interface CLUs, or Gate HTTP)
    manual_definitions: list = list(config_entry.options.get(CONF_MANUAL_OBJECTS, []))
    gate_options: dict = dict(config_entry.options.get(CONF_GATE) or {})
    gate_coordinator: GrentonGateCoordinator | None = None
    if gate_options.get(CONF_GATE_URL) and any(d.get("transport") == TRANSPORT_GATE for d in manual_definitions):
        gate_coordinator = GrentonGateCoordinator(
            hass,
            config_entry,
            gate_options[CONF_GATE_URL],
            gate_options.get(CONF_GATE_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
    manual_devices = build_manual_devices(manual_definitions, clus, coordinator, gate_coordinator, _LOGGER)
    _LOGGER.debug("Built %d manual device(s)", len(manual_devices))
    devices = devices + manual_devices + _connectivity_devices(clus, coordinator, gate_coordinator)
    _LOGGER.debug("Device details:")
    for device in devices:
        _LOGGER.debug("- Device %s (%s) with %d entity(ies)", device.type, device.id, len(device.entities))
        _LOGGER.debug("  Entities:")
        for entity in device.entities:
            _LOGGER.debug("  - Entity %s", entity.name)
    
    # Store runtime data
    config_entry.runtime_data = RuntimeData(
        coordinator=coordinator,
        devices=devices,
        gate_coordinator=gate_coordinator,
        structural_options=_structural_options(config_entry),
    )
    config_entry.async_on_unload(config_entry.add_update_listener(_async_options_updated))

    # Drop entities and devices that no longer exist in the freshly fetched interface
    _cleanup_orphans(hass, config_entry, devices)

    # Setup the coordinator
    await coordinator.async_setup()
    if gate_coordinator is not None:
        # Not first_refresh: an offline Gate must not block the UDP part.
        await gate_coordinator.async_refresh()
        webhook_id = gate_options.get(CONF_GATE_WEBHOOK_ID)
        if webhook_id:
            _register_gate_webhook(hass, config_entry, webhook_id, gate_coordinator)

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


def _connectivity_devices(clus: list, coordinator: GrentonCoordinator, gate_coordinator) -> list:
    """One diagnostic connectivity sensor per CLU and one for the Gate HTTP (#6)."""
    devices = []
    for clu in clus:
        device = GrentonDeviceManual(
            type="CLU",
            id=f"clu_{clu.id}",
            entities=[GrentonEntityConnectivity(coordinator, f"connectivity_{clu.id}", clu.name or clu.id, clu.id)],
        )
        device.apply_naming(clu.name or clu.id, None)
        devices.append(device)
    if gate_coordinator is not None:
        device = GrentonDeviceManual(
            type="GATE_HTTP",
            id="gate_http",
            entities=[GrentonEntityConnectivity(gate_coordinator, "connectivity_gate_http", "Gate HTTP", None)],
        )
        device.apply_naming("Grenton Gate HTTP", None)
        devices.append(device)
    return devices


def _register_gate_webhook(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    webhook_id: str,
    gate_coordinator: GrentonGateCoordinator,
) -> None:
    """Receive state changes pushed by the Gate (HttpRequest -> /api/webhook/<id>)."""

    async def handle(hass: HomeAssistant, webhook_id: str, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid json"}, status=400)
        updates = body if isinstance(body, list) else body.get("updates", [body]) if isinstance(body, dict) else []
        applied = gate_coordinator.push_updates(updates)
        return web.json_response({"g_status": "OK", "applied": applied})

    webhook.async_register(
        hass, "grenton", f"Grenton Gate ({config_entry.title})", webhook_id, handle,
        local_only=True, allowed_methods=["POST"],
    )
    config_entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))


def _structural_options(config_entry: ConfigEntry) -> tuple:
    return (
        repr(config_entry.options.get(CONF_MANUAL_OBJECTS, [])),
        repr(config_entry.options.get(CONF_GATE) or {}),
    )


async def _async_options_updated(hass: HomeAssistant, config_entry: GrentonConfigEntry) -> None:
    """Reload only when manual objects or Gate settings changed.

    Per-entity configuration (device class, unit, ...) is also stored in
    options but is applied live, so it must not trigger a reload.
    """
    if _structural_options(config_entry) != config_entry.runtime_data.structural_options:
        hass.config_entries.async_schedule_reload(config_entry.entry_id)


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