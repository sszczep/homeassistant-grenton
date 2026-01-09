from __future__ import annotations
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field

from ..domain.enums import GrentonValueCallType

class GrentonValueDto(BaseModel):
    cluId: str
    objectName: str
    index: str

class GrentonValueVariableDto(GrentonValueDto):
    callType: Literal[GrentonValueCallType.VARIABLE] = GrentonValueCallType.VARIABLE

class GrentonValueAttributeDto(GrentonValueDto):
    callType: Literal[GrentonValueCallType.ATTRIBUTE] = GrentonValueCallType.ATTRIBUTE

GrentonValueUnionDto = Annotated[
    Union[
        GrentonValueVariableDto,
        GrentonValueAttributeDto,
    ],
    Field(discriminator="callType"),
]