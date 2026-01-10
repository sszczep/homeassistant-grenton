from __future__ import annotations
from pydantic import Field
from typing import Union, Annotated

from .value_v2 import GrentonWidgetValueV2Dto
from .value_double import GrentonWidgetValueDoubleDto
from .on_off import GrentonWidgetOnOffDto
from .on_off_double import GrentonWidgetOnOffDoubleDto
from .dimmer_v2 import GrentonWidgetDimmerV2Dto
from .led import GrentonWidgetLedDto
from .contact_sensor import GrentonWidgetContactSensorDto
from .contact_sensor_double import GrentonWidgetContactSensorDoubleDto
from .slider import GrentonWidgetSliderDto
from .multisensor import GrentonWidgetMultisensorDto
from .roller_shutter import GrentonWidgetRollerShutterDto
from .roller_shutter_v3 import GrentonWidgetRollerShutterV3Dto

# Discriminated union using the 'type' field for secure deserialization
GrentonWidgetUnionDto = Annotated[
    Union[
        GrentonWidgetValueV2Dto,
        GrentonWidgetValueDoubleDto,
        GrentonWidgetOnOffDto,
        GrentonWidgetOnOffDoubleDto,
        GrentonWidgetDimmerV2Dto,
        GrentonWidgetLedDto,
        GrentonWidgetContactSensorDto,
        GrentonWidgetContactSensorDoubleDto,
        GrentonWidgetSliderDto,
        GrentonWidgetMultisensorDto,
        GrentonWidgetRollerShutterDto,
        GrentonWidgetRollerShutterV3Dto,
    ],
    Field(discriminator="type"),
]