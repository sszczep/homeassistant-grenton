"""Searchable entity selection with a local, immediate domain filter."""

from typing import Any

import voluptuous as vol
from homeassistant.helpers import selector


@selector.SELECTORS.register("grenton_entity")
class GrentonEntitySelector(selector.Selector):
    """Keep the selected entity ID as the form value; filtering is UI state."""

    selector_type = "grenton_entity"
    CONFIG_SCHEMA = vol.Schema({vol.Required("include_entities"): [str]})

    def __call__(self, value: Any) -> str:
        if not isinstance(value, str) or value not in self.config["include_entities"]:
            raise vol.Invalid("Select a configurable Grenton entity")
        return value
