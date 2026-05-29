"""Mapper for converting Scene widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.devices.scene import GrentonDeviceScene
from ..domain.enums import GrentonActionEventType
from ..domain.action import GrentonAction, GrentonActionScript
from ..domain.entities.base import BaseGrentonEntity
from ..domain.entities.scene_button import GrentonEntitySceneButton
from ..dto.widgets.scene import GrentonWidgetSceneDto


class DeviceSceneMapper:
    """Mapper for GrentonWidgetSceneDto to GrentonDeviceScene."""

    @staticmethod
    def to_domain(dto: GrentonWidgetSceneDto, coordinator: GrentonCoordinator) -> GrentonDeviceScene:
        device = GrentonDeviceScene(
            type=dto.type,
            id=dto.id,
            entities=[],
        )

        entities: list[BaseGrentonEntity] = []
        for component in dto.components:
            # Find the CLICK action of type SCRIPT — the only one supported for SCENE today.
            script_action: GrentonActionScript | None = None
            for action_dto in component.actions or []:
                action = GrentonAction.from_dto(action_dto)
                if action.event == GrentonActionEventType.CLICK and isinstance(action, GrentonActionScript):
                    script_action = action
                    break

            if script_action is None:
                continue

            entity = GrentonEntitySceneButton(
                coordinator=coordinator,
                id=f"{dto.id}_{component.rowId}",
                label=component.label,
                script_action=script_action,
                device_info=device.device_info,
            )
            entities.append(entity)

        device.entities = entities
        return device
