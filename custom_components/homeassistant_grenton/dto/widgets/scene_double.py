"""SCENE_DOUBLE widget ("Scena Podwójny", earlier "Open/Close").

The exact JSON of this widget is not documented, so parsing is tolerant to the
shapes used by the other double widgets:

    {"components": [ {label, rowId, actions: [...]}, {...} ]}        # like ON_OFF_DOUBLE
    {"componentLeft": {...}, "componentRight": {...}}               # like VALUE_DOUBLE
    {"components": [ {label, actions: [left action, right action]} ]}  # one row, two actions

Actions with an event name outside CLICK/ON/OFF (e.g. per-side events) are
kept; the original event name is used to label the button.
"""
from __future__ import annotations

from typing import Any, List, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from ...domain.enums import GrentonActionEventType
from ..action import GrentonActionUnionDto
from .base import GrentonWidgetDto

_ACTION_ADAPTER: TypeAdapter[GrentonActionUnionDto] = TypeAdapter(GrentonActionUnionDto)
_KNOWN_EVENTS = {event.value for event in GrentonActionEventType}


class GrentonSceneDoubleActionDto(BaseModel):
    """A parsed action plus the event name as found in the JSON."""

    action: GrentonActionUnionDto
    raw_event: str


class GrentonSceneDoubleComponentDto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = ""
    rowId: int | None = None
    actions: List[GrentonSceneDoubleActionDto] = Field(default_factory=list)

    @field_validator("actions", mode="before")
    @classmethod
    def _tolerant_actions(cls, value: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in value or []:
            if not isinstance(item, dict):
                continue
            raw_event = str(item.get("event", "CLICK"))
            data = dict(item)
            if raw_event not in _KNOWN_EVENTS:
                data["event"] = GrentonActionEventType.CLICK.value
            try:
                result.append({"action": _ACTION_ADAPTER.validate_python(data), "raw_event": raw_event})
            except ValidationError:
                continue
        return result


class GrentonWidgetSceneDoubleDto(GrentonWidgetDto):
    model_config = ConfigDict(extra="ignore")

    type: Literal["SCENE_DOUBLE"] = "SCENE_DOUBLE"
    label: str | None = None
    components: List[GrentonSceneDoubleComponentDto] | None = None
    componentLeft: GrentonSceneDoubleComponentDto | None = None
    componentRight: GrentonSceneDoubleComponentDto | None = None

    def all_components(self) -> list[tuple[str, GrentonSceneDoubleComponentDto]]:
        """(stable key, component) pairs in display order."""
        if self.componentLeft is not None or self.componentRight is not None:
            return [
                (key, component)
                for key, component in (("left", self.componentLeft), ("right", self.componentRight))
                if component is not None
            ]
        return [
            (str(component.rowId if component.rowId is not None else index), component)
            for index, component in enumerate(self.components or [])
        ]
