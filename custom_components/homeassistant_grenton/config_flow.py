import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (ConfigFlow, ConfigFlowResult, ConfigEntry)
from homeassistant.const import (CONF_IP_ADDRESS, CONF_PORT, CONF_PIN)
from homeassistant.core import callback

from .const import DOMAIN
from .domain.api.object_manager import (
    GrentonObjectManagerApi,
    GrentonObjectManagerAuthError,
    GrentonObjectManagerConnectionError,
    GrentonObjectManagerDataError
)
from .options_flow import GrentonOptionsFlow

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP_ADDRESS): str,
        vol.Required(CONF_PORT, default="9998"): str,
        vol.Required(CONF_PIN): str,
    }
)

class GrentonConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    
    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Get the options flow for this handler."""
        return GrentonOptionsFlow()
    
    async def _validate_and_fetch(self, user_input: dict[str, Any]):
        ip_address = user_input[CONF_IP_ADDRESS]
        port = user_input[CONF_PORT]
        pin = user_input[CONF_PIN]
        
        base_url = f"http://{ip_address}:{port}"
        
        try:
            async with GrentonObjectManagerApi(base_url) as api:
                return await api.fetch_mobile_interface(pin)
        except GrentonObjectManagerAuthError:
            raise InvalidAuth()
        except GrentonObjectManagerConnectionError:
            raise CannotConnect()
        except GrentonObjectManagerDataError:
            raise InvalidData()
        
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input:
            try:
                data = await self._validate_and_fetch(user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except InvalidData:
                errors["base"] = "invalid_data"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.exception("Unexpected exception: %s", e)
                errors["base"] = "unknown"
            else:
                interface_id = str(data.get("id"))
                
                await self.async_set_unique_id(interface_id)
                self._abort_if_unique_id_configured()
            
                return self.async_create_entry(
                    title=interface_id,
                    data={
                        **user_input,
                        "interface": data
                    }
                )
            
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )



class CannotConnect(Exception):
    pass

class InvalidAuth(Exception):
    pass

class InvalidData(Exception):
    pass