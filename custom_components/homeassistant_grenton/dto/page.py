from __future__ import annotations
import logging
from typing import List, Any
from pydantic import BaseModel, TypeAdapter, field_validator, ValidationError

from .widgets.union import GrentonWidgetUnionDto

_LOGGER = logging.getLogger(__name__)

class GrentonPageDto(BaseModel):
    name: str
    icon: str
    isFullscreenWidget: bool
    widgets: List[GrentonWidgetUnionDto]
    
    @field_validator("widgets", mode="before")
    @classmethod
    def skip_unsupported_widgets(cls, v: List[Any]) -> List[GrentonWidgetUnionDto]:
        widget_adapter: TypeAdapter[GrentonWidgetUnionDto] = TypeAdapter(GrentonWidgetUnionDto)
        result: List[GrentonWidgetUnionDto] = []

        for item in v:
            try:
                widget: GrentonWidgetUnionDto = widget_adapter.validate_python(item)
                result.append(widget)
            except ValidationError:
                _LOGGER.debug("Skipping unsupported widget: %s", item.get("type"))

        return result