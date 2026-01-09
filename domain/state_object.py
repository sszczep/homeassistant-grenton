from abc import ABC
from dataclasses import dataclass
from typing import Literal

from ..dto.value import GrentonValueUnionDto, GrentonValueAttributeDto, GrentonValueVariableDto

@dataclass
class GrentonStateObject(ABC):
    clu_id: str
    object_name: str
    index: str

    @staticmethod
    def from_dto(dto: GrentonValueUnionDto) -> "GrentonStateObject":
        if isinstance(dto, GrentonValueAttributeDto):
            return GrentonAttributeValueObject.create(dto)
        elif isinstance(dto, GrentonValueVariableDto): # type: ignore
            return GrentonVariableValueObject.create(dto)
        
        raise ValueError()
    
class GrentonAttributeValueObject(GrentonStateObject):
    call_type: Literal["ATTRIBUTE"] = "ATTRIBUTE"

    @staticmethod
    def create(dto: GrentonValueAttributeDto) -> "GrentonAttributeValueObject":
        return GrentonAttributeValueObject(
            clu_id=dto.cluId,
            object_name=dto.objectName,
            index=dto.index,
        )

class GrentonVariableValueObject(GrentonStateObject):
    call_type: Literal["VARIABLE"] = "VARIABLE"

    @staticmethod
    def create(dto: GrentonValueVariableDto) -> "GrentonVariableValueObject":
        return GrentonVariableValueObject(
            clu_id=dto.cluId,
            object_name=dto.objectName,
            index=dto.index,
        )