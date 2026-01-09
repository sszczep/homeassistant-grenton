from __future__ import annotations
from typing import Literal, Union, Annotated
from pydantic import BaseModel, Field

from ..domain.enums import GrentonActionCallType, GrentonActionEventType

class GrentonActionDto(BaseModel):
    event: GrentonActionEventType
    cluId: str
    objectName: str
    value: str

class GrentonActionVariableDto(GrentonActionDto):
    callType: Literal[GrentonActionCallType.VARIABLE] = GrentonActionCallType.VARIABLE
    index: str

class GrentonActionAttributeDto(GrentonActionDto):
    callType: Literal[GrentonActionCallType.ATTRIBUTE] = GrentonActionCallType.ATTRIBUTE
    index: str

class GrentonActionMethodDto(GrentonActionDto):
    callType: Literal[GrentonActionCallType.METHOD] = GrentonActionCallType.METHOD
    index: str

class GrentonActionScriptDto(GrentonActionDto):
    callType: Literal[GrentonActionCallType.SCRIPT] = GrentonActionCallType.SCRIPT

GrentonActionUnionDto = Annotated[
    Union[
        GrentonActionVariableDto,
        GrentonActionAttributeDto,
        GrentonActionMethodDto,
        GrentonActionScriptDto,
    ],
    Field(discriminator="callType"),
]