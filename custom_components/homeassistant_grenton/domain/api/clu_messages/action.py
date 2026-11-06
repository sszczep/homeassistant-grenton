from __future__ import annotations

from ...action import (
    GrentonAction,
    GrentonActionAttribute,
    GrentonActionMethod,
    GrentonActionScript,
    GrentonActionVariable,
    numeric_lua_literal,
)
from ...scene_arguments import quote_lua_string
from .base import GrentonCluApiRequest, GrentonCluApiResponse


class GrentonCluApiActionRequest(GrentonCluApiRequest):
    """Request to execute an action on the CLU.

    Supports variable, attribute, method, and script actions.
    """

    @staticmethod
    def from_action(
        action: GrentonAction, msg_id: str | None = None
    ) -> GrentonCluApiActionRequest:
        """Create request from a GrentonAction.

        Args:
            action: GrentonAction instance (Variable, Attribute, Method, or Script)
            msg_id: Optional message ID

        Returns:
            GrentonCluApiActionRequest with appropriate payload
        """
        if isinstance(action, GrentonActionVariable):
            value = (
                action.lua_value
                if action.lua_value is not None
                else numeric_lua_literal(action) or quote_lua_string(action.value)
            )
            payload = f"setVar({quote_lua_string(action.index)},{value})"
        elif isinstance(action, GrentonActionAttribute):
            value = (
                action.lua_value
                if action.lua_value is not None
                else numeric_lua_literal(action) or quote_lua_string(action.value)
            )
            payload = f"{action.object_name}:set({action.index},{value})"
        elif isinstance(action, GrentonActionMethod):
            if action.arguments is None:
                value = numeric_lua_literal(action) or quote_lua_string(action.value)
                payload = f"{action.object_name}:execute({action.index},{value})"
            else:
                parameters = ", ".join((action.index, *action.arguments))
                payload = f"{action.object_name}:execute({parameters})"
        elif isinstance(action, GrentonActionScript):
            payload = f"{action.object_name}({action.value})"
        else:
            raise TypeError(f"Unsupported action type: {type(action).__name__}")

        return GrentonCluApiActionRequest(payload, msg_id)


class GrentonCluApiActionResponse(GrentonCluApiResponse):
    """Response from action execution."""
