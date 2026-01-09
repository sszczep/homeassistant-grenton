from __future__ import annotations
from typing import Annotated, Literal, List, Union
from pydantic import Field

from .base import GrentonComponentDto
from ..value import GrentonValueUnionDto
from ..action import GrentonActionUnionDto
from ..range import GrentonRange

class GrentonComponentLedBaseDto(GrentonComponentDto):
    state: GrentonValueUnionDto
    actions: List[GrentonActionUnionDto]

class GrentonComponentLedButtonDto(GrentonComponentLedBaseDto):
    type: Literal["BUTTON_BISTABLE"] = "BUTTON_BISTABLE"
    image: str
    onIndication: str
    offIndication: str

class GrentonComponentLedHueDto(GrentonComponentLedBaseDto):
    type: Literal["SLIDER_HUE"] = "SLIDER_HUE"
    range: GrentonRange

class GrentonComponentLedSaturationDto(GrentonComponentLedBaseDto):
    type: Literal["SLIDER_SATURATION"] = "SLIDER_SATURATION"
    range: GrentonRange

class GrentonComponentLedBrightnessDto(GrentonComponentLedBaseDto):
    type: Literal["SLIDER_BRIGHTNESS"] = "SLIDER_BRIGHTNESS"
    range: GrentonRange

GrentonComponentLedUnionDto = Annotated[
    Union[
        GrentonComponentLedButtonDto,
        GrentonComponentLedHueDto,
        GrentonComponentLedSaturationDto,
        GrentonComponentLedBrightnessDto,
    ],
    Field(discriminator="type"),
]
