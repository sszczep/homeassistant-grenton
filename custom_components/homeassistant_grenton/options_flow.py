"""Options flow for Grenton integration."""
from typing import Any

import voluptuous as vol

import uuid

from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.helpers import selector

from .gate import (
    CONF_GATE,
    CONF_GATE_SCAN_INTERVAL,
    CONF_GATE_URL,
    DEFAULT_SCAN_INTERVAL,
    GrentonGateClient,
    GrentonGateError,
)
from .manual_objects import (
    CONF_MANUAL_OBJECTS,
    KINDS,
    KIND_BINARY_SENSOR,
    KIND_COVER,
    KIND_SENSOR,
    TRANSPORTS,
    TRANSPORT_GATE,
    TRANSPORT_UDP,
    InvalidGrentonId,
    find_interface_clu,
    parse_grenton_id,
)

class GrentonOptionsFlow(OptionsFlow):
    """Handle options flow for Grenton integration."""

    # Persist the selected entity unique_id for stable lookup
    selected_entity_uid: str | None = None
    # Accumulated config across steps
    entity_config: dict[str, Any] | None = None
    # Current step index
    current_step_index: int = 0

    # Dynamically redirect any unknown async_step_* methods to the generic handler
    def __getattr__(self, name: str):
        if name.startswith("async_step_"):
            async def _redirect(user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
                return await self.async_step_configure_entity(user_input)
            return _redirect
        raise AttributeError(name)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Main options menu."""
        menu = ["entity_list", "add_object", "gate_settings"]
        if self.config_entry.options.get(CONF_MANUAL_OBJECTS):
            menu.insert(2, "remove_object")
        return self.async_show_menu(step_id="init", menu_options=menu)

    # --- manual objects -----------------------------------------------------
    def _options_with(self, key: str, value: Any) -> dict[str, Any]:
        options = dict(self.config_entry.options)
        options[key] = value
        return options

    async def async_step_add_object(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                clu_name, _ = parse_grenton_id(user_input["grenton_id"])
            except InvalidGrentonId:
                errors["grenton_id"] = "invalid_grenton_id"
            else:
                transport = user_input["transport"]
                if transport == TRANSPORT_UDP:
                    clus = self.config_entry.runtime_data.coordinator.clus
                    if find_interface_clu(clu_name, clus) is None:
                        errors["grenton_id"] = "clu_not_in_interface"
                elif not (self.config_entry.options.get(CONF_GATE) or {}).get(CONF_GATE_URL):
                    errors["transport"] = "gate_not_configured"

            if not errors:
                kind = user_input["kind"]
                definition: dict[str, Any] = {
                    "id": uuid.uuid4().hex[:12],
                    "kind": kind,
                    "name": user_input["name"].strip(),
                    "grenton_id": user_input["grenton_id"].strip(),
                    "transport": user_input["transport"],
                    "area": (user_input.get("area") or "").strip(),
                }
                if kind in (KIND_SENSOR, KIND_BINARY_SENSOR):
                    definition["index"] = str(user_input.get("index") or "0").strip()
                    definition["variable"] = bool(user_input.get("variable"))
                if kind == KIND_BINARY_SENSOR:
                    definition["reversed"] = bool(user_input.get("reversed"))
                if kind == KIND_COVER:
                    definition["tilt"] = bool(user_input.get("tilt"))
                objects = list(self.config_entry.options.get(CONF_MANUAL_OBJECTS, []))
                objects.append(definition)
                return self.async_create_entry(title="", data=self._options_with(CONF_MANUAL_OBJECTS, objects))

        defaults = user_input or {}
        schema = vol.Schema({
            vol.Required("kind", default=defaults.get("kind", KINDS[0])): selector.SelectSelector(  # type: ignore[misc]
                selector.SelectSelectorConfig(options=KINDS, translation_key="manual_kind",
                                              mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Required("name", default=defaults.get("name", "")): str,
            vol.Required("grenton_id", default=defaults.get("grenton_id", "")): str,
            vol.Required("transport", default=defaults.get("transport", TRANSPORT_UDP)): selector.SelectSelector(  # type: ignore[misc]
                selector.SelectSelectorConfig(options=TRANSPORTS, translation_key="manual_transport",
                                              mode=selector.SelectSelectorMode.LIST)
            ),
            vol.Optional("area", default=defaults.get("area", "")): str,
            vol.Optional("index", default=defaults.get("index", "0")): str,
            vol.Optional("variable", default=defaults.get("variable", False)): bool,
            vol.Optional("reversed", default=defaults.get("reversed", False)): bool,
            vol.Optional("tilt", default=defaults.get("tilt", False)): bool,
        })
        return self.async_show_form(step_id="add_object", data_schema=schema, errors=errors)

    async def async_step_remove_object(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        objects: list[dict[str, Any]] = list(self.config_entry.options.get(CONF_MANUAL_OBJECTS, []))
        if user_input is not None:
            remove = set(user_input.get("objects") or [])
            kept = [o for o in objects if o.get("id") not in remove]
            return self.async_create_entry(title="", data=self._options_with(CONF_MANUAL_OBJECTS, kept))

        options = [
            selector.SelectOptionDict(value=o["id"], label=f"{o['name']} ({o['grenton_id']}, {o['transport']})")
            for o in objects
        ]
        return self.async_show_form(
            step_id="remove_object",
            data_schema=vol.Schema({
                vol.Required("objects"): selector.SelectSelector(  # type: ignore[misc]
                    selector.SelectSelectorConfig(options=options, multiple=True,
                                                  mode=selector.SelectSelectorMode.LIST)
                ),
            }),
        )

    async def async_step_gate_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current: dict[str, Any] = dict(self.config_entry.options.get(CONF_GATE) or {})
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input.get(CONF_GATE_URL, "").strip()
            if url:
                if not url.startswith(("http://", "https://")):
                    url = f"http://{url}"
                try:
                    await GrentonGateClient(self.hass, url).test()
                except GrentonGateError:
                    errors["base"] = "cannot_connect_gate"
            if not errors:
                gate = {CONF_GATE_URL: url, CONF_GATE_SCAN_INTERVAL: int(user_input[CONF_GATE_SCAN_INTERVAL])}
                return self.async_create_entry(title="", data=self._options_with(CONF_GATE, gate))

        return self.async_show_form(
            step_id="gate_settings",
            data_schema=vol.Schema({
                vol.Optional(CONF_GATE_URL, default=current.get(CONF_GATE_URL, "")): str,
                vol.Required(
                    CONF_GATE_SCAN_INTERVAL,
                    default=current.get(CONF_GATE_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=2, max=3600)),
            }),
            errors=errors,
        )

    async def async_step_entity_list(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show list of configurable entities."""
        # Get all configurable entities from the integration
        entities = self._get_configurable_entities()
        # Collect only entities that have a valid entity_id
        entity_ids = [e.entity_id for e in entities if e.entity_id]
        
        if not entity_ids:
            return self.async_abort(reason="no_configurable_entities")
        
        if user_input is not None:
            # User selected an entity to configure (entity_id)
            selected = user_input.get("entity")
            if selected:
                # Resolve to unique_id for stable internal reference
                matched = next((e for e in entities if e.entity_id == selected), None)
                if not matched:
                    return self.async_abort(reason="entity_not_found")
                self.selected_entity_uid = matched.unique_id
                return await self.async_step_configure_entity()
        
        # Build entity selection schema using EntitySelector with include_entities
        return self.async_show_form(
            step_id="entity_list",
            data_schema=vol.Schema({
                vol.Required("entity"): selector.EntitySelector(  # type: ignore[misc]
                    selector.EntitySelectorConfig(
                        include_entities=sorted(entity_ids),
                        multiple=False,
                    )
                ),
            })
        )

    async def async_step_configure_entity(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Configure entity - generic step handler."""
        from .domain.entities.configurable import ConfigurableEntity
        from .domain.entities.base import BaseGrentonEntity
        
        entities = self._get_configurable_entities()
        # Look up by stable unique_id captured during selection
        entity: BaseGrentonEntity | None = next(
            (e for e in entities if e.unique_id == self.selected_entity_uid),
            None,
        )
        
        if not entity or not isinstance(entity, ConfigurableEntity):
            return self.async_abort(reason="entity_not_found")
        
        current_config: dict[str, Any] = getattr(entity, "_config", {})
        
        # Initialize accumulated config if not exists
        if self.entity_config is None:
            self.entity_config = {}
            self.current_step_index = 0
        
        if user_input is not None:
            # Accumulate data from this step
            self.entity_config.update(user_input)
            self.current_step_index += 1
        
        # Get schema instance
        schema_instance = entity._get_schema_instance()  # type: ignore[reportPrivateUsage]
        if not schema_instance:
            return self.async_abort(reason="entity_not_configurable")
        
        # Get steps list (with explicit step_id defined per configurable)
        steps = getattr(schema_instance, "steps", [])
        if not steps:
            return self.async_abort(reason="entity_not_configurable")

        # Check if we're done with all steps
        if self.current_step_index >= len(steps):
            options = await entity.apply_configuration(self.entity_config)
            self.entity_config = None
            self.current_step_index = 0
            return self.async_create_entry(title="", data=options)
        
        # Build schema for current step
        step_def = steps[self.current_step_index]
        result = step_def.builder(current_config, self.entity_config)
        # If the schema signals completion, apply and finish
        if getattr(result, "complete", False):
            options = await entity.apply_configuration(self.entity_config)
            self.entity_config = None
            self.current_step_index = 0
            return self.async_create_entry(title="", data=options)
        # Prefer schema-provided step_id override, else the definition's step_id
        step_id = result.step_id or step_def.step_id
        
        # Extract schema, description, and placeholders from StepResult
        schema = result.schema
        custom_description = result.description
        schema_placeholders = result.placeholders
        
        # Merge flow-level and schema-specific placeholders
        placeholders: dict[str, Any] = {
            "entity_name": entity.label,
            "step_number": str(self.current_step_index + 1),
            "total_steps": str(len(steps)),
            "custom_description": custom_description,
            **schema_placeholders,  # Schema-specific placeholders override defaults
        }
        
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            description_placeholders=placeholders,
        )

    def _get_configurable_entities(self) -> list[Any]:
        """Get all configurable entities from the integration."""
        from .domain.entities.configurable import ConfigurableEntity
        from .integration_config import GrentonConfigEntry
        from .domain.entities.base import BaseGrentonEntity
        
        config_entry: GrentonConfigEntry = self.config_entry  # type: ignore
        runtime_data = config_entry.runtime_data
        
        entities: list[BaseGrentonEntity] = []
        for device in runtime_data.devices:
            for entity in device.entities:
                if isinstance(entity, ConfigurableEntity):
                    entities.append(entity)
        
        return entities
