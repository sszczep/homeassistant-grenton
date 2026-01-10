from __future__ import annotations
from typing import Optional
from pydantic import BaseModel

from ..value import GrentonValueUnionDto
from ..action import GrentonActionUnionDto

class GrentonObjectRollerShutterV3Dto(BaseModel):
    state: GrentonValueUnionDto
    up: Optional[GrentonValueUnionDto] = None
    down: Optional[GrentonValueUnionDto] = None
    loadCurrent: Optional[GrentonValueUnionDto] = None
    overcurrent: Optional[GrentonValueUnionDto] = None
    voltageType: Optional[GrentonValueUnionDto] = None
    position: GrentonValueUnionDto
    lamelPosition: GrentonValueUnionDto
    lamelMoveTimeout: Optional[GrentonValueUnionDto] = None
    distributedLogicGroup: Optional[GrentonValueUnionDto] = None
    reversePosition: Optional[GrentonValueUnionDto] = None
    blindsUpMaxTime: Optional[GrentonValueUnionDto] = None
    blindsDownMaxTime: Optional[GrentonValueUnionDto] = None
    mechanicalOffset: Optional[GrentonValueUnionDto] = None
    setPositionAction: GrentonActionUnionDto
    setLamelPositionAction: GrentonActionUnionDto
    calibrationAction: Optional[GrentonActionUnionDto] = None
    setBlindsMaxTimeAction: Optional[GrentonActionUnionDto] = None
    setLamelMoveTimeoutAction: Optional[GrentonActionUnionDto] = None
    moveUpAction: GrentonActionUnionDto
    moveDownAction: GrentonActionUnionDto
    startAction: GrentonActionUnionDto
    stopAction: Optional[GrentonActionUnionDto] = None
    holdAction: Optional[GrentonActionUnionDto] = None
    holdUpAction: Optional[GrentonActionUnionDto] = None
    holdDownAction: Optional[GrentonActionUnionDto] = None
    setRollerBlockedAction: GrentonActionUnionDto
    lamelStartAction: Optional[GrentonActionUnionDto] = None
    setMechanicalOffsetAction: Optional[GrentonActionUnionDto] = None
    setBlindsUpMaxTimeAction: Optional[GrentonActionUnionDto] = None
    setBlindsDownMaxTimeAction: Optional[GrentonActionUnionDto] = None