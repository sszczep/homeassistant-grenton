"""Mapper for SCENE_DOUBLE widgets: one button entity per scene action."""

from ..coordinator import GrentonCoordinator
from ..domain.action import GrentonAction
from ..domain.devices.scene_double import GrentonDeviceSceneDouble
from ..domain.entities.base import BaseGrentonEntity
from ..domain.entities.scene_button import GrentonEntitySceneButton
from ..dto.widgets.scene_double import GrentonWidgetSceneDoubleDto


class DeviceSceneDoubleMapper:
    @staticmethod
    def to_domain(dto: GrentonWidgetSceneDoubleDto, coordinator: GrentonCoordinator) -> GrentonDeviceSceneDouble:
        device = GrentonDeviceSceneDouble(
            type=dto.type, id=dto.id, entities=[], widget_label=(dto.label or "").strip() or None
        )
        entities: list[BaseGrentonEntity] = []
        base_label = (dto.label or "").strip()

        for key, component in dto.all_components():
            label = component.label.strip() or base_label or dto.id
            actions = component.actions
            if not actions:
                continue
            if len(actions) == 1:
                buttons = [(f"{dto.id}_{key}", label, actions[0])]
            else:
                # One row with several actions (e.g. left/right): one button each,
                # named after the event; the row label names the device
                if not device.widget_label:
                    device.widget_label = label
                buttons = [
                    (f"{dto.id}_{key}_{index}", item.raw_event.replace("_", " ").capitalize(), item)
                    for index, item in enumerate(actions)
                ]
            for uid, button_label, item in buttons:
                entities.append(
                    GrentonEntitySceneButton(
                        coordinator=coordinator,
                        id=uid,
                        label=button_label,
                        script_action=GrentonAction.from_dto(item.action),
                        device_info=device.device_info,
                    )
                )

        device.entities = entities
        return device
