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
from .dto.mobile_interface import GrentonMobileInterfaceDto
from .dto.page import GrentonPageDto
from .naming import (
    CONF_DEVICE_NAMES,
    CONF_PAGE_AREAS,
    auto_device_name,
    resolve_device_name,
    resolve_page_area,
)

_LOGGER = logging.getLogger(__name__)

CONF_CUSTOMIZE_NAMES = "customize_names"
CONF_AREA = "area"

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
        self._pages: list[GrentonPageDto] = []
        self._page_index = 0
        # form field key -> widget id, for the page currently shown
        self._field_to_widget: dict[str, str] = {}
    
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
        """Ask whether the user wants to customize device names and areas."""
        if user_input is not None:
            if not user_input.get(CONF_CUSTOMIZE_NAMES):
                return await self._async_finish()
            try:
                interface = GrentonMobileInterfaceDto(**self._base_data["interface"])
            except Exception as e:  # validation of the fetched interface
                _LOGGER.exception("Cannot parse mobile interface: %s", e)
                return self.async_abort(reason="invalid_data")
            self._pages = [page for page in interface.pages if page.widgets]
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

    async def async_step_page_names(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """One form per interface page: area + a name field per widget."""
        page = self._pages[self._page_index]

        if user_input is not None:
            self._page_areas[page.name] = str(user_input.get(CONF_AREA, "")).strip()
            widgets_by_id = {widget.id: widget for widget in page.widgets}
            for field, widget_id in self._field_to_widget.items():
                value = str(user_input.get(field, "")).strip()
                widget = widgets_by_id[widget_id]
                if value and value != auto_device_name(widget):
                    self._device_names[widget_id] = value
                else:
                    self._device_names.pop(widget_id, None)

            self._page_index += 1
            if self._page_index >= len(self._pages):
                return await self._async_finish()
            page = self._pages[self._page_index]

        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_AREA,
                default=resolve_page_area(page.name, self._page_areas) or "",
            ): str,
        }
        self._field_to_widget = {}
        for widget in page.widgets:
            # The key doubles as the visible label (no translation exists for it);
            # the widget id keeps it unique.
            field = f"{auto_device_name(widget)} ({widget.type}, {widget.id})"
            self._field_to_widget[field] = widget.id
            schema[vol.Optional(field, default=resolve_device_name(widget, self._device_names))] = str

        return self.async_show_form(
            step_id="page_names",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "page": page.name,
                "step": str(self._page_index + 1),
                "total": str(len(self._pages)),
                "count": str(len(page.widgets)),
            },
        )

    async def _async_finish(self) -> ConfigFlowResult:
        data = {
            **self._base_data,
            CONF_DEVICE_NAMES: self._device_names,
            CONF_PAGE_AREAS: self._page_areas,
        }
        if self._is_reconfigure:
            return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data=data)
        return self.async_create_entry(title=str(self._base_data["interface"].get("id")), data=data)



class CannotConnect(Exception):
    pass

class InvalidAuth(Exception):
    pass

class InvalidData(Exception):
    pass