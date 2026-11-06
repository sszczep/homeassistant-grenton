"""Mapper for converting Scene widget DTO to domain device."""

from ..coordinator import GrentonCoordinator
from ..domain.action import GrentonAction, GrentonActionScript
from ..domain.devices.scene import GrentonDeviceScene
from ..domain.entities.base import BaseGrentonEntity
from ..domain.entities.scene_button import GrentonEntitySceneButton
from ..domain.enums import GrentonActionEventType
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
            # Preserve the existing preference for scripts when a component has
            # several CLICK actions; otherwise use the first CLICK action.
            click_action: GrentonAction | None = None
            for action_dto in component.actions or []:
                action = GrentonAction.from_dto(action_dto)
                if action.event == GrentonActionEventType.CLICK:
                    if click_action is None:
                        click_action = action
                    if isinstance(action, GrentonActionScript):
                        click_action = action
                        break

            if click_action is None:
                continue

            entity = GrentonEntitySceneButton(
                coordinator=coordinator,
                id=f"{dto.id}_{component.rowId}",
                label=component.label,
                script_action=click_action,
                device_info=device.device_info,
            )
            entities.append(entity)

        device.entities = entities
        return device
