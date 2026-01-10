from __future__ import annotations
from typing import Any

import logging
import asyncio

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .domain.clu import GrentonClu
from .domain.encryption import GrentonEncryption
from .domain.state_object import GrentonStateObject
from .domain.action import GrentonAction
from .domain.api.clu import GrentonCluApi
from .state import GrentonState, GrentonCluState, GrentonCluStateVariableKey, GrentonCluStateAttributeKey, GrentonValue
from .domain.api.clu_messages import GrentonCluApiActionRequest

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class GrentonCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, clus: list[GrentonClu], encryption: GrentonEncryption):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
        )
        
        self.config_entry = config_entry
        self.clus = clus
        self.encryption = encryption
        self.state = GrentonState(clus={clu.id: GrentonCluState() for clu in clus})
        
        # Map CLU IDs to their API instances
        self._apis: dict[str, GrentonCluApi] = {}
        
        # Initialize API instances for each CLU
        for clu in clus:
            self._apis[clu.id] = GrentonCluApi(clu, encryption)

    async def _async_update_data(self): # type: ignore
        return self.state
    
    async def _send_ping(self, clu_id: str) -> None:
        api = self._apis.get(clu_id)
        if not api:
            _LOGGER.warning("[%s] No API found for CLU during ping", clu_id)
            return
        
        try:
            success = await api.ping()
            if not success:
                _LOGGER.warning("[%s] Ping failed", clu_id)
        except Exception as e:
            _LOGGER.error("[%s] Error during ping: %s", clu_id, e)
    
    async def _ping_loop(self) -> None:
        while True:
            try:
                # Ping every 5 seconds
                ping_interval = 5
                await asyncio.sleep(ping_interval)
                
                tasks = [self._send_ping(clu_id) for clu_id in self._apis.keys()]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                _LOGGER.debug("Ping loop cancelled")
                break
            except Exception as e:
                _LOGGER.error("Unexpected error in ping loop: %s", e)
    
    async def _send_register(self, clu_id: str) -> None:
        api = self._apis.get(clu_id)
        if not api:
            _LOGGER.warning("[%s] No API found for CLU during state registration", clu_id)
            return
        
        clu_state = self.state.clus[clu_id]
        
        # Check if there are any states to register
        if not clu_state.has_states_to_register():
            _LOGGER.debug("[%s] No component states to register", clu_id)
            return
        
        try:
            keys = clu_state.get_subscription_order()
            values = await api.register_component_states(keys)
            if values:
                # Update state by zipping keys with values
                for key, value in zip(keys, values):
                    if isinstance(key, GrentonCluStateVariableKey):
                        clu_state.set_variable(key, value)
                    elif isinstance(key, GrentonCluStateAttributeKey): # type: ignore
                        clu_state.set_attribute(key, value)
                self.async_set_updated_data(self.state.__dict__)
        except Exception as e:
            _LOGGER.error("[%s] Error during registration: %s", clu_id, e)
    
    async def _register_loop(self) -> None:
        while True:
            try:
                # Only register if there are actual states to register
                clu_ids_to_register = [
                    clu_id for clu_id, clu_state in self.state.clus.items()
                    if clu_state.has_states_to_register()
                ]
                
                if not clu_ids_to_register:
                    # No states to register, wait longer before checking again
                    await asyncio.sleep(45)
                    continue
                
                # Registration interval
                registration_interval = 45
                await asyncio.sleep(registration_interval)
                
                tasks = [self._send_register(clu_id) for clu_id in clu_ids_to_register]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                _LOGGER.debug("Register loop cancelled")
                break
            except Exception as e:
                _LOGGER.error("Unexpected error in register loop: %s", e)
    
    async def execute_action(self, action: GrentonAction) -> None:
        api = self._apis.get(action.clu_id)
        if not api:
            _LOGGER.warning("[%s] No API found for CLU during action execution", action.clu_id)
            return
        
        try:
            success = await api.execute_action(action)
            if not success:
                _LOGGER.warning("[%s] Action execution failed for payload: %s", action.clu_id, GrentonCluApiActionRequest.from_action(action).payload)
        except Exception as e:
            _LOGGER.error("[%s] Error executing action: %s", action.clu_id, e)
    
    async def _process_report(self, clu_id: str, values: list[GrentonValue]) -> None:
        """Process a report from a CLU and update state values.
        
        Args:
            clu_id: The CLU identifier
            values: Parsed values from the report
        """
        clu_state = self.state.clus[clu_id]
        clu_state.update_state(values)
        
        self.async_set_updated_data(self.state.__dict__)
        _LOGGER.debug("[%s] Processed report with %d values", clu_id, len(values))
    
    def register_component_state(self, state: GrentonStateObject) -> None:
        self.state.register_state(state)
    
    async def async_setup(self) -> None:
        # Connect all APIs
        connection_tasks: list[Any] = []
        for clu in self.clus:
            api = self._apis[clu.id]
            connection_tasks.append(self._connect_api(api))
        
        # Wait for all connections to complete
        await asyncio.gather(*connection_tasks, return_exceptions=True)
        
        # Send initial pings to establish sessions
        ping_tasks = [self._send_ping(clu_id) for clu_id in self._apis.keys()]
        if ping_tasks:
            await asyncio.gather(*ping_tasks, return_exceptions=True)
        
        # Send initial registrations
        register_tasks = [self._send_register(clu_id) for clu_id in self.state.clus.keys()]
        if register_tasks:
            await asyncio.gather(*register_tasks, return_exceptions=True)
        
        # Start background tasks
        self._ping_task = asyncio.create_task(self._ping_loop())
        self._register_task = asyncio.create_task(self._register_loop())
    
    async def _connect_api(self, api: GrentonCluApi) -> None:
        """Connect a single API instance."""
        try:
            success = await api.connect()
            if not success:
                _LOGGER.error("Failed to connect API for CLU %s", api.clu.id)
                return
            
            # Set subscription callback to handle reports
            if api.protocol:
                async def handle_subscription(values: list[GrentonValue]) -> None:
                    await self._process_report(api.clu.id, values)
                api.protocol.subscription_callback = handle_subscription
            else:
                _LOGGER.error("Failed to set subscription callback for CLU %s", api.clu.id)
        except Exception as e:
            _LOGGER.error("Error connecting API for CLU %s: %s", api.clu.id, e)
    
    async def async_shutdown(self) -> None:
        # Cancel background tasks
        if hasattr(self, '_ping_task'):
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            _LOGGER.debug("Cancelled ping task")
        
        if hasattr(self, '_register_task'):
            self._register_task.cancel()
            try:
                await self._register_task
            except asyncio.CancelledError:
                pass
            _LOGGER.debug("Cancelled register task")
        
        # Disconnect all APIs
        disconnect_tasks: list[Any] = []
        for api in self._apis.values():
            disconnect_tasks.append(self._disconnect_api(api))
        
        await asyncio.gather(*disconnect_tasks, return_exceptions=True)
        self._apis.clear()
    
    async def _disconnect_api(self, api: GrentonCluApi) -> None:
        """Disconnect a single API instance."""
        try:
            await api.disconnect()
        except Exception as e:
            _LOGGER.error("Error disconnecting API for CLU %s: %s", api.clu.id, e)
    
    def get_value_for_component(self, state: GrentonStateObject) -> GrentonValue | None:
        """Get the value for a component from the state."""
        return self.state.get_value_for_component(state)
