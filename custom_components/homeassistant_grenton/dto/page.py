from __future__ import annotations
import logging
from typing import List, Any
from pydantic import BaseModel, TypeAdapter, field_validator, ValidationError

from .widgets.union import GrentonWidgetUnionDto

_LOGGER = logging.getLogger(__name__)

_WIDGET_ADAPTER: TypeAdapter[GrentonWidgetUnionDto] = TypeAdapter(GrentonWidgetUnionDto)

# Widget types already reported in this run, to avoid flooding the log
_REPORTED: set[str] = set()


def _summarize(error: ValidationError, limit: int = 3) -> str:
    parts = []
    for item in error.errors()[:limit]:
        location = ".".join(str(p) for p in item.get("loc", ()))
        parts.append(f"{location}: {item.get('msg')}")
    more = len(error.errors()) - limit
    if more > 0:
        parts.append(f"(+{more} more)")
    return "; ".join(parts)


def validate_widget(item: Any) -> tuple[GrentonWidgetUnionDto | None, ValidationError | None]:
    try:
        return _WIDGET_ADAPTER.validate_python(item), None
    except ValidationError as error:
        return None, error


class GrentonPageDto(BaseModel):
    name: str
    icon: str
    isFullscreenWidget: bool
    widgets: List[GrentonWidgetUnionDto]

    @field_validator("widgets", mode="before")
    @classmethod
    def skip_unsupported_widgets(cls, v: List[Any]) -> List[GrentonWidgetUnionDto]:
        result: List[GrentonWidgetUnionDto] = []

        for item in v:
            widget, error = validate_widget(item)
            if widget is not None:
                result.append(widget)
                continue
            widget_type = str(item.get("type")) if isinstance(item, dict) else "?"
            # Full error at debug level, a one-line summary once per type as warning (#5)
            _LOGGER.debug("Skipping widget %s, error: %s", widget_type, error)
            if widget_type not in _REPORTED:
                _REPORTED.add(widget_type)
                _LOGGER.warning(
                    "Skipping widget type %s (unsupported or unexpected format): %s. "
                    "Download the integration diagnostics and attach them to an issue.",
                    widget_type, _summarize(error) if error else "",
                )

        return result
