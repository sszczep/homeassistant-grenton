"""Bistable ON_OFF controls exposed as switches by default."""

from homeassistant.components.switch import SwitchEntity

from .on_off import GrentonEntityOnOff


class GrentonEntityBistableSwitch(GrentonEntityOnOff, SwitchEntity):
    """Bistable switch with an optional light presentation."""
