"""Device naming helpers shared by the config flow and entry setup.

Device names are derived from the widget labels found in the Grenton mobile
interface. The user may override them (and the suggested area per page)
during the config / reconfigure flow; overrides are stored in the config
entry data under CONF_DEVICE_NAMES / CONF_PAGE_AREAS.
"""
from __future__ import annotations

from typing import Any

CONF_DEVICE_NAMES = "device_names"  # {widget_id: custom device name}
CONF_PAGE_AREAS = "page_areas"      # {page_name: area name ("" = no area)}


def _labels_of(widget: Any) -> list[str]:
    labels: list[str] = []

    label = getattr(widget, "label", None)
    if isinstance(label, str):
        labels.append(label)

    for component in getattr(widget, "components", None) or []:
        component_label = getattr(component, "label", None)
        if isinstance(component_label, str):
            labels.append(component_label)

    for attr in ("componentLeft", "componentRight"):
        component = getattr(widget, attr, None)
        component_label = getattr(component, "label", None) if component else None
        if isinstance(component_label, str):
            labels.append(component_label)

    # Unique, non-empty, order preserved
    seen: set[str] = set()
    result: list[str] = []
    for item in (lbl.strip() for lbl in labels):
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def auto_device_name(widget: Any) -> str:
    """Return a human readable default name for a widget."""
    labels = _labels_of(widget)
    if labels:
        return " / ".join(labels)
    return f"{getattr(widget, 'type', 'Grenton')} {widget.id}"


def resolve_device_name(widget: Any, overrides: dict[str, str] | None) -> str:
    custom = (overrides or {}).get(widget.id, "").strip()
    return custom or auto_device_name(widget)


def resolve_page_area(page_name: str, overrides: dict[str, str] | None) -> str | None:
    """Area suggested for devices of a page. Defaults to the page name."""
    if overrides is not None and page_name in overrides:
        return overrides[page_name].strip() or None
    return page_name.strip() or None
