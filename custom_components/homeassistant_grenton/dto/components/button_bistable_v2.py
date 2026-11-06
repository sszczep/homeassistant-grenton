from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field

from ..action import GrentonActionUnionDto
from ..value import GrentonValueUnionDto
from .base import GrentonComponentDto


class GrentonComponentButtonBistableV2Dto(GrentonComponentDto):
    type: Literal["BUTTON_BISTABLE_V2"] = "BUTTON_BISTABLE_V2"
    icon: str | None = Field(
        default=None, validation_alias=AliasChoices("image", "icon")
    )
    state: GrentonValueUnionDto
    actions: list[GrentonActionUnionDto]
    onIndication: str
    offIndication: str
