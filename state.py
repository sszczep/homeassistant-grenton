from __future__ import annotations
from typing import Union, Any
from dataclasses import dataclass
from .domain.state_object import GrentonStateObject, GrentonAttributeValueObject, GrentonVariableValueObject

# Type alias for Grenton values (string, boolean, number, or None)
GrentonValue = Union[str, bool, int, float, None]


def cast_string_to_grenton_value(value: str) -> GrentonValue:
    """Cast string value to appropriate Python type."""
    stripped_value = value.strip().strip('"')  # Remove surrounding quotes
    
    # Handle nil/None values
    if stripped_value.lower() == 'nil':
        return None
    
    # Handle boolean values
    if stripped_value.lower() == 'true':
        return True
    if stripped_value.lower() == 'false':
        return False
    
    # Handle numeric values
    try:
        # Try to convert to int first
        return int(stripped_value)
    except ValueError:
        try:
            # Then try float
            return float(stripped_value)
        except ValueError:
            # Keep as string
            return stripped_value


@dataclass(frozen=True)
class GrentonCluStateVariableKey:
    """Key for identifying a CLU state variable."""
    name: str


@dataclass(frozen=True)
class GrentonCluStateAttributeKey:
    """Key for identifying a CLU state attribute."""
    object_name: str
    name: str


@dataclass
class GrentonCluStateVariable:
    """Represents a CLU state variable."""
    name: str
    value: GrentonValue
    
    def __init__(self, name: str, value: GrentonValue | None = None):
        self.name = name
        self.value = value if value is not None else ""


@dataclass
class GrentonCluStateAttribute:
    """Represents a CLU state attribute."""
    object_name: str
    name: str
    value: GrentonValue
    
    def __init__(self, object_name: str, name: str, value: GrentonValue | None = None):
        self.object_name = object_name
        self.name = name
        self.value = value if value is not None else ""
    
    @property
    def key(self) -> GrentonCluStateAttributeKey:
        """Get the key for this attribute."""
        return GrentonCluStateAttributeKey(self.object_name, self.name)

class GrentonCluState:
    """State management for a single CLU with efficient dictionary-based storage."""
    
    def __init__(self):
        # Variables: dict[variable_name, GrentonCluStateVariable]
        self.variables: dict[GrentonCluStateVariableKey, GrentonCluStateVariable] = {}
        
        # Attributes: dict[(object_name, attribute_name), GrentonCluStateAttribute]
        self.attributes: dict[GrentonCluStateAttributeKey, GrentonCluStateAttribute] = {}
        
        # Maintain subscription order
        self._subscription_order: list[GrentonCluStateVariableKey | GrentonCluStateAttributeKey] = []
    
    def add_variable(self, name: str, initial_value: GrentonValue | None = None) -> None:
        """Add a variable to the state if it doesn't exist."""
        key = GrentonCluStateVariableKey(name)
        if key not in self.variables:
            self.variables[key] = GrentonCluStateVariable(name, initial_value)
            self._subscription_order.append(key)
    
    def add_attribute(self, object_name: str, name: str, initial_value: GrentonValue | None = None) -> None:
        """Add an attribute to the state if it doesn't exist."""
        key = GrentonCluStateAttributeKey(object_name, name)
        if key not in self.attributes:
            self.attributes[key] = GrentonCluStateAttribute(object_name, name, initial_value)
            self._subscription_order.append(key)
    
    def get_variable(self, key: GrentonCluStateVariableKey) -> GrentonValue | None:
        """Get a variable value by key."""
        var = self.variables.get(key)
        return var.value if var else None
    
    def get_attribute(self, key: GrentonCluStateAttributeKey) -> GrentonValue | None:
        """Get an attribute value by key."""
        attr = self.attributes.get(key)
        return attr.value if attr else None
    
    def set_variable(self, key: GrentonCluStateVariableKey, value: GrentonValue) -> None:
        """Set a variable value by key."""
        if key in self.variables:
            self.variables[key].value = self._cast_value(value)
    
    def set_attribute(self, key: GrentonCluStateAttributeKey, value: GrentonValue) -> None:
        """Set an attribute value by key."""
        if key in self.attributes:
            self.attributes[key].value = self._cast_value(value)
    
    def _cast_value(self, value: Any) -> GrentonValue:
        """Cast raw string values to appropriate Python types."""
        # Handle already proper types
        if isinstance(value, (bool, int, float, str)):
            return value
        
        # Convert string representations to proper types
        if isinstance(value, str):
            return self._cast_string_value(value)
        
        # Fallback for unexpected types
        return str(value)
    
    def _cast_string_value(self, value: str) -> GrentonValue:
        """Cast string value to appropriate Python type."""
        return cast_string_to_grenton_value(value)
    
    def has_states_to_register(self) -> bool:
        """Check if there are any states to register."""
        return bool(self._subscription_order)
    
    def get_subscription_order(self) -> list[GrentonCluStateVariableKey | GrentonCluStateAttributeKey]:
        """Get the order for subscription registration."""
        return self._subscription_order
    
    def update_state(self, values: list[GrentonValue]) -> None:
        """Update state with report values.
        
        Args:
            values: List of values in subscription order
        """
        keys = self.get_subscription_order()
        
        for key, value in zip(keys, values):
            if isinstance(key, GrentonCluStateVariableKey):
                self.variables[key].value = value
            else:
                self.attributes[key].value = value


@dataclass
class GrentonState:
    clus: dict[str, GrentonCluState]
    
    def __init__(self, clus: dict[str, GrentonCluState] | None = None):
        self.clus = clus if clus is not None else {}
    
    def register_state(self, state: GrentonStateObject) -> None:
        """Register a state for tracking."""
        # Get or create CLU state
        clu_state = self.clus.get(state.clu_id)
        if not clu_state:
            return None

        if isinstance(state, GrentonVariableValueObject):
            clu_state.add_variable(state.index)
        elif isinstance(state, GrentonAttributeValueObject):
            clu_state.add_attribute(state.object_name, state.index)
    
    def get_value_for_component(self, state: GrentonStateObject) -> GrentonValue | None:
        """Get the value for a component from the appropriate CLU state."""
        clu_state = self.clus.get(state.clu_id)
        if not clu_state:
            return None
        
        if isinstance(state, GrentonVariableValueObject):
            return clu_state.get_variable(GrentonCluStateVariableKey(state.index))
        elif isinstance(state, GrentonAttributeValueObject):
            return clu_state.get_attribute(GrentonCluStateAttributeKey(state.object_name, state.index))
        
        return None
