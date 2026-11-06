from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field

from ..components.button_bistable_v2 import GrentonComponentButtonBistableV2Dto
from .base import GrentonWidgetDto


class GrentonWidgetOnOffDoubleDto(GrentonWidgetDto):
    type: Literal["ON_OFF_DOUBLE"] = "ON_OFF_DOUBLE"
    icon: str | None = Field(
        default=None, validation_alias=AliasChoices("image", "icon")
    )
    components: list[GrentonComponentButtonBistableV2Dto]
