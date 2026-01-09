from abc import ABC
from dataclasses import dataclass

from .enums import GrentonActionEventType

from ..dto.action import GrentonActionAttributeDto, GrentonActionVariableDto, GrentonActionMethodDto, GrentonActionScriptDto, GrentonActionUnionDto

@dataclass
class GrentonAction(ABC):
    clu_id: str
    object_name: str
    event: GrentonActionEventType
    value: str

    @staticmethod
    def from_dto(dto: GrentonActionUnionDto) -> "GrentonAction":
        if isinstance(dto, GrentonActionAttributeDto):
            return GrentonActionAttribute.create(dto)
        elif isinstance(dto, GrentonActionVariableDto):
            return GrentonActionVariable.create(dto)
        elif isinstance(dto, GrentonActionMethodDto):
            return GrentonActionMethod.create(dto)
        elif isinstance(dto, GrentonActionScriptDto): # type: ignore
            return GrentonActionScript.create(dto)
        
        raise ValueError()
    
@dataclass
class GrentonActionAttribute(GrentonAction):
    index: str

    @staticmethod
    def create(dto: GrentonActionAttributeDto) -> "GrentonActionAttribute":
        return GrentonActionAttribute(
            clu_id=dto.cluId,
            object_name=dto.objectName,
            event=dto.event,
            value=dto.value,
            index=dto.index,
        )
    
@dataclass
class GrentonActionVariable(GrentonAction):
    index: str

    @staticmethod
    def create(dto: GrentonActionVariableDto) -> "GrentonActionVariable":
        return GrentonActionVariable(
            clu_id=dto.cluId,
            object_name=dto.objectName,
            event=dto.event,
            value=dto.value,
            index=dto.index,
        )
    
@dataclass
class GrentonActionMethod(GrentonAction):
    index: str

    @staticmethod
    def create(dto: GrentonActionMethodDto) -> "GrentonActionMethod":
        return GrentonActionMethod(
            clu_id=dto.cluId,
            object_name=dto.objectName,
            event=dto.event,
            value=dto.value,
            index=dto.index,
        )
    
@dataclass
class GrentonActionScript(GrentonAction):

    @staticmethod
    def create(dto: GrentonActionScriptDto) -> "GrentonActionScript":
        return GrentonActionScript(
            clu_id=dto.cluId,
            object_name=dto.objectName,
            event=dto.event,
            value=dto.value,
        )