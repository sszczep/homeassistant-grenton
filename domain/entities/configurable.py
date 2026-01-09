from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, Optional, TypeVar, cast, get_args, get_origin

import voluptuous as vol

from ...coordinator import GrentonCoordinator


@dataclass
class StepResult:
    """Result returned by a configuration step builder."""
    schema: vol.Schema
    description: str = ""
    placeholders: Dict[str, Any] = field(default_factory=lambda: {})
    # Optional override for step_id, allowing schema to choose a specific id
    step_id: Optional[str] = None
    # When true, the flow should immediately complete without showing a form
    complete: bool = False


@dataclass
class StepDefinition:
    """Configuration step definition with explicit step_id and builder."""
    step_id: str
    builder: Callable[[Dict[str, Any], Dict[str, Any]], StepResult]


class BaseGrentonEntityConfigurationSchema(ABC):
    """Base configuration schema for Grenton entities."""

    # Override in subclass: property that returns list of StepDefinition
    # Each step has explicit step_id and builder(current_config, accumulated_data) -> StepResult
    @property
    def steps(self) -> list[StepDefinition]:
        return []


C = TypeVar("C", bound=BaseGrentonEntityConfigurationSchema)


class ConfigurableEntity(Generic[C]):
    """Mixin to handle per-entity configuration persisted in config entry options."""

    config_category = "entities"

    # These attributes are provided by the concrete HA entity/base classes.
    coordinator: GrentonCoordinator
    hass: Any
    unique_id: str

    def __init__(self: "ConfigurableEntity[Any]", **schema_kwargs: Any) -> None:
        self._configured: bool = False
        self._schema_kwargs: Dict[str, Any] = schema_kwargs
        defaults = self.default_config()
        loaded = self._load_config(defaults)
        self._config: Dict[str, Any] = loaded

    def default_config(self) -> Dict[str, Any]:
        """Defaults to use when no configuration was saved."""
        schema = self._get_schema_instance()
        if schema and hasattr(schema, "defaults"):
            return schema.defaults()  # type: ignore[attr-defined]
        return {}

    def build_config_schema(self, current: Dict[str, Any]):
        """Return a voluptuous schema for configuration."""
        schema = self._get_schema_instance()
        if schema and hasattr(schema, "build"):
            return schema.build(current)
        raise NotImplementedError

    def _get_schema_instance(self) -> Optional[Any]:
        schema_cls = self._get_schema_cls()
        if schema_cls is None:
            return None
        try:
            return schema_cls(**self._schema_kwargs)  # type: ignore[call-arg]
        except Exception:
            try:
                return schema_cls()  # type: ignore[call-arg]
            except Exception:
                return None

    def _get_schema_cls(self) -> Optional[type]:
        for base in getattr(type(self), "__orig_bases__", []):
            if get_origin(base) is ConfigurableEntity:
                args = get_args(base)
                if args and isinstance(args[0], type):
                    return args[0]
        return None

    def _config_key(self) -> str:
        return self.unique_id

    def _load_config(self, defaults: Dict[str, Any]) -> Dict[str, Any]:
        options = cast(Dict[str, Any], self.coordinator.config_entry.options) if self.coordinator.config_entry else {}
        category = cast(Dict[str, Any], options.get(self.config_category, {}))
        existing = cast(Optional[Dict[str, Any]], category.get(self._config_key()))

        if isinstance(existing, dict):
            self._configured = True
            return existing

        self._configured = False
        return defaults

    def _merge_config_into_options(self, config: Dict[str, Any]) -> Dict[str, Any]:
        options = dict(cast(Dict[str, Any], self.coordinator.config_entry.options)) if self.coordinator.config_entry else {}
        category = dict(options.get(self.config_category, {})) if isinstance(options.get(self.config_category, {}), dict) else {}
        category[self._config_key()] = config
        options[self.config_category] = category
        return options

    async def apply_configuration(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        """Persist configuration and return merged options for the flow."""
        self._config = user_input
        self._configured = True
        return self._merge_config_into_options(user_input)