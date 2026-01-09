from __future__ import annotations
from pydantic import Field
from typing import Union, Annotated

from .value_v2 import GrentonWidgetValueV2Dto
from .value_double import GrentonWidgetValueDoubleDto
from .on_off import GrentonWidgetOnOffDto
from .on_off_double import GrentonWidgetOnOffDoubleDto
from .dimmer_v2 import GrentonWidgetDimmerV2Dto
from .led import GrentonWidgetLedDto

# Discriminated union using the 'type' field for secure deserialization
GrentonWidgetUnionDto = Annotated[
    Union[
        GrentonWidgetValueV2Dto,
        GrentonWidgetValueDoubleDto,
        GrentonWidgetOnOffDto,
        GrentonWidgetOnOffDoubleDto,
        GrentonWidgetDimmerV2Dto,
        GrentonWidgetLedDto,
    ],
    Field(discriminator="type"),
]