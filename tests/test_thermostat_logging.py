"""Thermostat diagnostics identify the device and each relevant Grenton source."""

import logging
from types import SimpleNamespace

import pytest
from test_thermostat_configuration import thermostat

from custom_components.homeassistant_grenton.domain.state_object import (
    GrentonAttributeValueObject,
    GrentonVariableValueObject,
)


@pytest.mark.parametrize("registered", [False, True])
def test_schedule_warning_identifies_device_entity_and_grenton_object(
    caplog, registered
):
    data = '"a' * 672 + "+00:30"
    entity, _ = thermostat(values={"9": data})
    if registered:
        entity.device_entry = SimpleNamespace(
            name="Imported thermostat", name_by_user="Salon - Termostat"
        )
    else:
        entity.entity_id = None  # Also useful before HA assigns an entity ID.
    with caplog.at_level(logging.WARNING):
        entity._analyse_schedule()
        entity._analyse_schedule()
    assert len(caplog.records) == 1  # Repeated coordinator updates do not spam.
    message = caplog.records[0].getMessage()
    assert "Salon - Termostat" in message if registered else entity.label in message
    assert f"widget={entity.unique_id}" in message
    if registered:
        assert f"entity={entity.entity_id}" in message
    assert "scheduleData=clu1/THERMOSTAT1.9" in message
    assert "maxTemperature=clu1/THERMOSTAT1.11" in message
    assert "Invalid encoded schedule temperature" in message
    assert repr('"a') in message
    assert data not in message


def test_schedule_diagnostics_use_each_actual_binding_even_across_clus(caplog):
    entity, coord = thermostat()
    entity.states["scheduleData"] = GrentonVariableValueObject("clu1", "", "WeekData")
    entity.states["maxTemperature"] = GrentonAttributeValueObject(
        "clu2", "OTHER_THERMOSTAT", "11"
    )
    coord.get_value_for_component.side_effect = lambda state: (
        '"a' * 672 + "+00:30" if state.index == "WeekData" else 30
    )
    with caplog.at_level(logging.WARNING):
        entity._analyse_schedule()
    message = caplog.records[0].getMessage()
    assert "scheduleData=clu1/variable:WeekData" in message
    assert "maxTemperature=clu2/OTHER_THERMOSTAT.11" in message
