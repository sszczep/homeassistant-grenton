from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field

from ..components.button_bistable import GrentonComponentButtonBistableDto
from .base import GrentonWidgetDto


class GrentonWidgetOnOffDto(GrentonWidgetDto):
    type: Literal["ON_OFF"] = "ON_OFF"
    icon: str | None = Field(
        default=None, validation_alias=AliasChoices("image", "icon")
    )
    components: list[GrentonComponentButtonBistableDto]
