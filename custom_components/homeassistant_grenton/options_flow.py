"""Options flow for Grenton integration."""

from typing import Any
from uuid import uuid4

import voluptuous as vol

import uuid


from .gate import (
    CONF_GATE,
    CONF_GATE_SCAN_INTERVAL,
    CONF_GATE_URL,
    CONF_GATE_WEBHOOK_ID,
    DEFAULT_SCAN_INTERVAL,
    GrentonGateClient,
    GrentonGateError,
)
from .manual_objects import (
    CONF_MANUAL_OBJECTS,
    KINDS,
    KIND_BINARY_SENSOR,
    KIND_COVER,
    KIND_LED_CHANNEL,
    KIND_SENSOR,
    LED_CHANNELS,
    TRANSPORTS,
    TRANSPORT_GATE,
    TRANSPORT_UDP,
    InvalidGrentonId,
    find_interface_clu,
    parse_grenton_id,
)
from homeassistant.config_entries import ConfigFlowResult, OptionsFlowWithReload
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .clu_settings import (
    CONF_SUBSCRIPTION_ID,
    MAX_SUBSCRIPTION_ID,
    MIN_SUBSCRIPTION_ID,
    subscription_id,
    validate_subscription_id,
)
from .domain.entities.clu_variables import (
    CluVariableConfigurationSchema,
    normalize_variable,
    variable_definitions,
    variable_options,
)
from .entity_picker import GrentonEntitySelector
from .frontend import async_register_scene_editor
from .read_policy import (
    CONF_CLU_READ_SETTINGS,
    CONF_SLOW_READ_INTERVAL,
    MAX_SLOW_READ_INTERVAL,
    MIN_SLOW_READ_INTERVAL,
    slow_read_interval,
    validate_slow_read_interval,
)


class GrentonOptionsFlow(OptionsFlowWithReload):
    """Handle options flow for Grenton integration."""

    automatic_reload = False

    # Persist the selected entity unique_id for stable lookup
    selected_entity_uid: str | None = None
    # Accumulated config across steps
    entity_config: dict[str, Any] | None = None
    # Current step index
    current_step_index: int = 0

    # Dynamically redirect any unknown async_step_* methods to the generic handler
    def __getattr__(self, name: str):
        if name.startswith("async_step_"):

            async def _redirect(
                user_input: dict[str, Any] | None = None,
            ) -> ConfigFlowResult:
                return await self.async_step_configure_entity(user_input)

            return _redirect
        raise AttributeError(name)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Separate per-CLU connection settings from individual entities."""
        # Startup can precede frontend setup. Ensure selectors exist when a
        # browser actually opens configuration, including after an update.
        await async_register_scene_editor(self.hass, notify_clients=True)
        menu = ["clu_read_settings", "entity_list", "add_object", "gate_settings"]
        try:
            has_manual = bool(self.config_entry.options.get(CONF_MANUAL_OBJECTS))
        except (AttributeError, ValueError):  # flow not bound to an entry yet
            has_manual = False
        if has_manual:
            menu.insert(3, "remove_object")
        return self.async_show_menu(step_id="init", menu_options=menu)

    # --- manual objects -----------------------------------------------------
    def _options_with(self, key: str, value: Any) -> dict[str, Any]:
        """Options with one structural key replaced; reloads the entry on save."""
        options = dict(self.config_entry.options)
        options[key] = value
        # Manual objects and Gate settings change devices/transports
        self.automatic_reload = True
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
                if kind == KIND_LED_CHANNEL:
                    definition["channel"] = user_input.get("channel") or "w"
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
            vol.Optional("channel", default=defaults.get("channel", "w")): selector.SelectSelector(  # type: ignore[misc]
                selector.SelectSelectorConfig(options=LED_CHANNELS, translation_key="led_channel",
                                              mode=selector.SelectSelectorMode.DROPDOWN)
            ),
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
                gate: dict[str, Any] = {
                    CONF_GATE_URL: url,
                    CONF_GATE_SCAN_INTERVAL: int(user_input[CONF_GATE_SCAN_INTERVAL]),
                }
                if user_input.get("push"):
                    from homeassistant.components import webhook
                    gate[CONF_GATE_WEBHOOK_ID] = current.get(CONF_GATE_WEBHOOK_ID) or webhook.async_generate_id()
                return self.async_create_entry(title="", data=self._options_with(CONF_GATE, gate))

        return self.async_show_form(
            step_id="gate_settings",
            data_schema=vol.Schema({
                vol.Optional(CONF_GATE_URL, default=current.get(CONF_GATE_URL, "")): str,
                vol.Required(
                    CONF_GATE_SCAN_INTERVAL,
                    default=current.get(CONF_GATE_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=2, max=3600)),
                vol.Optional("push", default=bool(current.get(CONF_GATE_WEBHOOK_ID))): bool,
            }),
            errors=errors,
            description_placeholders={"webhook_url": self._webhook_url(current.get(CONF_GATE_WEBHOOK_ID))},
        )

    def _webhook_url(self, webhook_id: str | None) -> str:
        if not webhook_id:
            return "—"
        from homeassistant.helpers.network import NoURLAvailableError, get_url
        try:
            base = get_url(self.hass, allow_external=False, prefer_external=False)
        except NoURLAvailableError:
            base = "http://<adres-HA>:8123"
        return f"{base}/api/webhook/{webhook_id}"

    def _configured_clus(self) -> dict[str, str]:
        """Allow CLU configuration even while the integration is unloaded."""
        return {
            clu["id"]: clu.get("name", clu["id"])
            for clu in self.config_entry.data.get("interface", {}).get("clus", [])
        }

    async def async_step_clu_read_settings(self, user_input=None):
        clus = self._configured_clus()
        errors = {}
        if user_input is not None:
            clu_id = user_input.get("clu_id")
            if clu_id in clus:
                self._clu_id = clu_id
                return await self.async_step_clu_configuration()
            errors["clu_id"] = "invalid_configuration"
        return self.async_show_form(
            step_id="clu_read_settings",
            data_schema=vol.Schema(
                {
                    vol.Required("clu_id"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": clu_id, "label": f"{name} ({clu_id})"}
                                for clu_id, name in clus.items()
                            ]
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_clu_configuration(self, user_input=None):
        """Group controller settings and variable management under one CLU."""
        # HA menu headers do not receive placeholders; the description names
        # the selected CLU instead.
        return self.async_show_menu(
            step_id="clu_configuration",
            menu_options=["clu_read_interval", "clu_variables"],
            description_placeholders={
                "clu_name": self._configured_clus()[self._clu_id]
            },
        )

    async def async_step_clu_read_interval(self, user_input=None):
        errors = {}
        interval = slow_read_interval(self.config_entry.options, self._clu_id)
        saved_subscription_id = subscription_id(self.config_entry.options, self._clu_id)
        selected_subscription_id = saved_subscription_id
        if user_input is not None:
            try:
                interval = validate_slow_read_interval(
                    user_input.get(CONF_SLOW_READ_INTERVAL)
                )
            except vol.Invalid:
                errors[CONF_SLOW_READ_INTERVAL] = "invalid_configuration"
            try:
                selected_subscription_id = validate_subscription_id(
                    user_input.get(CONF_SUBSCRIPTION_ID, saved_subscription_id)
                )
            except vol.Invalid:
                errors[CONF_SUBSCRIPTION_ID] = "invalid_configuration"
            if not errors:
                options = dict(self.config_entry.options)
                settings = dict(options.get(CONF_CLU_READ_SETTINGS, {}))
                settings[self._clu_id] = {
                    **settings.get(self._clu_id, {}),
                    CONF_SLOW_READ_INTERVAL: interval,
                    CONF_SUBSCRIPTION_ID: selected_subscription_id,
                }
                options[CONF_CLU_READ_SETTINGS] = settings
                runtime = getattr(self.config_entry, "runtime_data", None)
                try:
                    if runtime is not None:
                        await runtime.coordinator.async_set_subscription_id(
                            self._clu_id, selected_subscription_id
                        )
                        if interval != slow_read_interval(
                            self.config_entry.options, self._clu_id
                        ):
                            await runtime.coordinator.async_set_slow_read_interval(
                                self._clu_id, interval
                            )
                except HomeAssistantError:
                    errors["base"] = "cannot_apply_configuration"
                else:
                    self.automatic_reload = False
                    return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="clu_read_interval",
            last_step=True,
            errors=errors,
            description_placeholders={
                "clu_name": self._configured_clus()[self._clu_id]
            },
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SLOW_READ_INTERVAL, default=interval
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_SLOW_READ_INTERVAL,
                            max=MAX_SLOW_READ_INTERVAL,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Required(
                        CONF_SUBSCRIPTION_ID, default=selected_subscription_id
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_SUBSCRIPTION_ID,
                            max=MAX_SUBSCRIPTION_ID,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )

    async def async_step_entity_list(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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

        # The selector filters locally while retaining HA's native entity search.
        return self.async_show_form(
            step_id="entity_list",
            last_step=False,
            data_schema=vol.Schema(
                {
                    # HA cannot infer an initial value for a custom selector.
                    vol.Required(
                        "entity", description={"suggested_value": ""}
                    ): GrentonEntitySelector({"include_entities": sorted(entity_ids)}),
                }
            ),
        )

    async def async_step_configure_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure entity - generic step handler."""
        from .domain.entities.base import BaseGrentonEntity
        from .domain.entities.configurable import ConfigurableEntity

        entities = self._get_configurable_entities()
        # Look up by stable unique_id captured during selection
        entity: BaseGrentonEntity | None = next(
            (e for e in entities if e.unique_id == self.selected_entity_uid),
            None,
        )

        if not entity or not isinstance(entity, ConfigurableEntity):
            return self.async_abort(reason="entity_not_found")

        current_config: dict[str, Any] = getattr(entity, "_config", {})
        errors: dict[str, str] = {}

        # Initialize accumulated config if not exists
        if self.entity_config is None:
            self.entity_config = {}
            self.current_step_index = 0
            try:
                await entity.async_prepare_configuration()
            except HomeAssistantError:
                errors["base"] = "cannot_read_configuration"

        # Get schema instance
        schema_instance = entity._get_schema_instance()  # type: ignore[reportPrivateUsage]
        if not schema_instance:
            return self.async_abort(reason="entity_not_configurable")

        # Get steps list (with explicit step_id defined per configurable)
        steps = getattr(schema_instance, "steps", [])
        if not steps:
            return self.async_abort(reason="entity_not_configurable")

        if user_input is not None:
            result = steps[self.current_step_index].builder(
                current_config,
                self.entity_config,
            )
            try:
                validated = result.schema(user_input)
                if result.validator is not None:
                    validated = result.validator(validated)
            except vol.Invalid as err:
                field = str(err.path[0]) if err.path else "base"
                errors[field] = "invalid_configuration"
                # Keep entered values visible while the user fixes the error.
                current_config = {**current_config, **user_input}
            else:
                self.entity_config.update(validated)
                self.current_step_index += 1

        # Check if we're done with all steps
        if self.current_step_index >= len(steps):
            self.automatic_reload = getattr(entity, "reload_after_configuration", False)
            try:
                options = await entity.apply_configuration(self.entity_config)
            except HomeAssistantError:
                # Keep the popup and draft open when a device write fails.
                errors["base"] = "cannot_apply_configuration"
                self.current_step_index = len(steps) - 1
                if len(steps) == 1:
                    self.entity_config = {}
                current_config = {**current_config, **(user_input or {})}
            else:
                self.entity_config = None
                self.current_step_index = 0
                return self.async_create_entry(title="", data=options)

        # Build schema for current step
        step_def = steps[self.current_step_index]
        result = step_def.builder(current_config, self.entity_config)
        # If the schema signals completion, apply and finish
        if getattr(result, "complete", False):
            self.automatic_reload = getattr(entity, "reload_after_configuration", False)
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
            "entity_name": entity.name or entity.label,
            "step_number": str(self.current_step_index + 1),
            "total_steps": str(len(steps)),
            "custom_description": custom_description,
            **schema_placeholders,  # Schema-specific placeholders override defaults
        }

        return self.async_show_form(
            step_id=step_id,
            last_step=self.current_step_index == len(steps) - 1,
            data_schema=schema,
            description_placeholders=placeholders,
            errors=errors,
        )

    def _get_configurable_entities(self) -> list[Any]:
        """Get all configurable entities from the integration."""
        from .domain.entities.configurable import ConfigurableEntity
        from .integration_config import GrentonConfigEntry

        config_entry: GrentonConfigEntry = self.config_entry  # type: ignore
        runtime_data = getattr(config_entry, "runtime_data", None)
        if runtime_data is None:
            return []

        entities: list[Any] = []
        for device in runtime_data.devices:
            for entity in device.entities:
                if isinstance(entity, ConfigurableEntity):
                    entities.append(entity)

        for entity in getattr(runtime_data, "clu_entities", []):
            if isinstance(entity, ConfigurableEntity):
                entities.append(entity)
        return entities

    async def async_step_clu_variables(self, user_input=None):
        """Manage custom variables on the selected CLU."""
        variables = variable_definitions(self.config_entry.options, self._clu_id)
        if user_input is not None:
            operation = user_input.get("operation")
            if operation == "add":
                self._variable_id = uuid4().hex
                self._variable_current = {}
                self.entity_config = {}
                self.current_step_index = 0
                return await self.async_step_configure_clu_variable()
            if operation in ("edit", "remove") and variables:
                self._variable_operation = operation
                return await self.async_step_clu_variable_select()
        return self.async_show_form(
            step_id="clu_variables",
            last_step=False,
            description_placeholders={
                "clu_name": self._configured_clus()[self._clu_id]
            },
            data_schema=vol.Schema(
                {
                    vol.Required("operation"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["add", *(["edit", "remove"] if variables else [])],
                            translation_key="clu_variable_operations",
                        )
                    )
                }
            ),
        )

    async def async_step_clu_variable_select(self, user_input=None):
        variables = variable_definitions(self.config_entry.options, self._clu_id)
        errors = {}
        if user_input is not None:
            variable_id = user_input.get("variable_id")
            if variable_id not in variables:
                errors["variable_id"] = "invalid_configuration"
            elif self._variable_operation == "remove":
                self.automatic_reload = True
                return self.async_create_entry(
                    title="",
                    data=variable_options(
                        self.config_entry.options, self._clu_id, variable_id, None
                    ),
                )
            else:
                self._variable_id = variable_id
                self._variable_current = variables[variable_id]
                self.entity_config = {}
                self.current_step_index = 0
                return await self.async_step_configure_clu_variable()
        return self.async_show_form(
            step_id="clu_variable_remove"
            if self._variable_operation == "remove"
            else "clu_variable_select",
            last_step=self._variable_operation == "remove",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("variable_id"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "value": key,
                                    "label": f"{config['label']} ({config['variable_name']})",
                                }
                                for key, config in variables.items()
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_configure_clu_variable(self, user_input=None):
        # A normal entity selection uses the generic configurable-entity handler.
        if not hasattr(self, "_variable_id"):
            return await self.async_step_configure_entity(user_input)
        schema = CluVariableConfigurationSchema(
            variables=variable_definitions(self.config_entry.options, self._clu_id),
            variable_id=self._variable_id,
        )
        steps = schema.steps
        current = self._variable_current
        errors = {}
        if user_input is not None:
            result = steps[self.current_step_index].builder(current, self.entity_config)
            try:
                validated = result.schema(user_input)
                if result.validator:
                    validated = result.validator(validated)
            except vol.Invalid as error:
                errors[str(error.path[0]) if error.path else "base"] = (
                    "invalid_configuration"
                )
                current = {**current, **user_input}
            else:
                self.entity_config.update(validated)
                self.current_step_index += 1
        if self.current_step_index < len(steps):
            step = steps[self.current_step_index]
            result = step.builder(current, self.entity_config)
            if not result.complete:
                return self.async_show_form(
                    step_id=step.step_id,
                    last_step=self.current_step_index == len(steps) - 1,
                    data_schema=result.schema,
                    errors=errors,
                    description_placeholders={
                        "entity_name": current.get("label")
                        or self._configured_clus()[self._clu_id]
                    },
                )
        self.automatic_reload = True
        return self.async_create_entry(
            title="",
            data=variable_options(
                self.config_entry.options,
                self._clu_id,
                self._variable_id,
                normalize_variable(self.entity_config),
            ),
        )

    async def async_step_configure_sensor_class(self, user_input=None):
        if hasattr(self, "_variable_id"):
            return await self.async_step_configure_clu_variable(user_input)
        return await self.async_step_configure_entity(user_input)

    async def async_step_configure_value_v2_type(self, user_input=None):
        return await self.async_step_configure_entity(user_input)

    async def async_step_configure_sensor_unit(self, user_input=None):
        if hasattr(self, "_variable_id"):
            return await self.async_step_configure_clu_variable(user_input)
        return await self.async_step_configure_entity(user_input)

    async def async_step_clu_variable_remove(self, user_input=None):
        return await self.async_step_clu_variable_select(user_input)
