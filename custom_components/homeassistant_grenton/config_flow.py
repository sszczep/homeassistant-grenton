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
from .entity_settings import PageModel, apply_page_input, build_pages, page_schema
from .naming import CONF_DEVICE_NAMES, CONF_PAGE_AREAS

_LOGGER = logging.getLogger(__name__)

CONF_CUSTOMIZE_NAMES = "customize_names"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP_ADDRESS): str,
        vol.Required(CONF_PORT, default="9998"): str,
        vol.Required(CONF_PIN): str,
    }
)

class GrentonConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._base_data: dict[str, Any] = {}
        self._is_reconfigure = False
        self._device_names: dict[str, str] = {}
        self._page_areas: dict[str, str] = {}
        self._options: dict[str, Any] = {}
        self._pages: list[PageModel] = []
        self._page_index = 0
    
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

                self._base_data = {**user_input, "interface": data}
                self._is_reconfigure = False
                self._device_names = {}
                self._page_areas = {}
                self._options = {}
                return await self.async_step_naming()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Re-fetch the mobile interface for the existing config entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

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
                self._abort_if_unique_id_mismatch(reason="wrong_interface")

                self._base_data = {**user_input, "interface": data}
                self._is_reconfigure = True
                self._device_names = dict(entry.data.get(CONF_DEVICE_NAMES) or {})
                self._page_areas = dict(entry.data.get(CONF_PAGE_AREAS) or {})
                self._options = dict(entry.options)
                return await self.async_step_naming()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA,
                {
                    CONF_IP_ADDRESS: entry.data.get(CONF_IP_ADDRESS),
                    CONF_PORT: entry.data.get(CONF_PORT),
                },
            ),
            errors=errors,
        )


    async def async_step_naming(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask whether to customize names, areas, units and precision."""
        if user_input is not None:
            if not user_input.get(CONF_CUSTOMIZE_NAMES):
                return await self._async_finish()
            try:
                self._pages = build_pages(self.hass, self._base_data["interface"], self._options)
            except Exception as e:  # validation of the fetched interface
                _LOGGER.exception("Cannot parse mobile interface: %s", e)
                return self.async_abort(reason="invalid_data")
            self._page_index = 0
            if not self._pages:
                return await self._async_finish()
            return await self.async_step_page_names()

        return self.async_show_form(
            step_id="naming",
            data_schema=vol.Schema(
                {vol.Required(CONF_CUSTOMIZE_NAMES, default=False): bool}
            ),
        )

    def _names_data(self) -> dict[str, Any]:
        return {CONF_DEVICE_NAMES: self._device_names, CONF_PAGE_AREAS: self._page_areas}

    async def async_step_page_names(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """One form per interface page: area, device and entity names, units, precision."""
        language = self.hass.config.language
        page = self._pages[self._page_index]

        if user_input is not None:
            data, self._options = apply_page_input(page, user_input, self._names_data(), self._options, language)
            self._device_names = data[CONF_DEVICE_NAMES]
            self._page_areas = data[CONF_PAGE_AREAS]
            self._page_index += 1
            if self._page_index >= len(self._pages):
                return await self._async_finish()
            page = self._pages[self._page_index]

        return self.async_show_form(
            step_id="page_names",
            data_schema=page_schema(page, self._names_data(), self._options, language),
            description_placeholders={
                "page": page.name,
                "step": str(self._page_index + 1),
                "total": str(len(self._pages)),
                "count": str(len(page.devices)),
            },
        )

    async def _async_finish(self) -> ConfigFlowResult:
        data = {**self._base_data, **self._names_data()}
        if self._is_reconfigure:
            entry = self._get_reconfigure_entry()
            from .domain.entities.base import CONF_ENTITY_OVERRIDES
            from .entity_settings import apply_name_overrides
            apply_name_overrides(
                self.hass, entry,
                entry.options.get(CONF_ENTITY_OVERRIDES),
                self._options.get(CONF_ENTITY_OVERRIDES),
            )
            return self.async_update_reload_and_abort(entry, data=data, options=self._options)
        return self.async_create_entry(
            title=str(self._base_data["interface"].get("id")), data=data, options=self._options
        )


class CannotConnect(Exception):
    pass

class InvalidAuth(Exception):
    pass

class InvalidData(Exception):
    pass