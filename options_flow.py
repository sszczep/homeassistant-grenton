"""Options flow for Grenton integration."""
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.helpers import selector

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
        """Manage the options - show list of entities to configure."""
        return await self.async_step_entity_list(user_input)

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
            entity.apply_configuration(self.entity_config)
            self.entity_config = None
            self.current_step_index = 0
            return self.async_create_entry(title="", data={})
        
        # Build schema for current step
        step_def = steps[self.current_step_index]
        result = step_def.builder(current_config, self.entity_config)
        # If the schema signals completion, apply and finish
        if getattr(result, "complete", False):
            entity.apply_configuration(self.entity_config)
            self.entity_config = None
            self.current_step_index = 0
            return self.async_create_entry(title="", data={})
        # Prefer schema-provided step_id override, else the definition's step_id
        step_id = result.step_id or step_def.step_id
        
        # Extract schema, description, and placeholders from StepResult
        schema = result.schema
        custom_description = result.description
        schema_placeholders = result.placeholders
        
        # Merge flow-level and schema-specific placeholders
        placeholders: dict[str, Any] = {
            "entity_name": entity.name,
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
