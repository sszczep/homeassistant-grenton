from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field

from ..action import GrentonActionUnionDto
from ..value import GrentonValueUnionDto
from .base import GrentonComponentDto


class GrentonComponentButtonBistableDto(GrentonComponentDto):
    type: Literal["BUTTON_BISTABLE"] = "BUTTON_BISTABLE"
    icon: str | None = Field(
        default=None, validation_alias=AliasChoices("image", "icon")
    )
    state: GrentonValueUnionDto
    actions: list[GrentonActionUnionDto]
    onIndication: str
    offIndication: str
