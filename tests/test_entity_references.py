"""Compact entity references preserve actual call semantics and editor data."""

from copy import deepcopy

import pytest

from custom_components.homeassistant_grenton.domain.action import (
    GrentonActionAttribute,
    GrentonActionMethod,
    GrentonActionScript,
    GrentonActionVariable,
)
from custom_components.homeassistant_grenton.domain.entity_references import (
    action_reference,
    state_reference,
)
from custom_components.homeassistant_grenton.domain.enums import GrentonActionEventType
from custom_components.homeassistant_grenton.domain.state_object import (
    GrentonAttributeValueObject,
    GrentonVariableValueObject,
)

EVENT = GrentonActionEventType.ON


@pytest.mark.parametrize(
    "source,target,call_type",
    [
        (GrentonAttributeValueObject("clu", "RELAY1", "0"), "RELAY1.0", "ATTRIBUTE"),
        (
            GrentonVariableValueObject("clu", "", "RoomTemperature"),
            "RoomTemperature",
            "VARIABLE",
        ),
        (
            GrentonVariableValueObject("clu", "Variables", "RoomTemperature"),
            "Variables.RoomTemperature",
            "VARIABLE",
        ),
    ],
)
def test_compact_sources_leave_editor_configuration_unchanged(
    source, target, call_type
):
    original = deepcopy(source.source_attributes)
    assert state_reference(source) == {
        "clu_id": "clu",
        "call_type": call_type,
        "object": target,
    }
    assert source.source_attributes == original
    assert "object" not in original


@pytest.mark.parametrize(
    "action,target,call_type",
    [
        (
            GrentonActionAttribute("clu", "Relay", EVENT, "1", "0"),
            "Relay.0",
            "ATTRIBUTE",
        ),
        (GrentonActionVariable("clu", "", EVENT, "255", "Level"), "Level", "VARIABLE"),
        (
            GrentonActionVariable("clu", "Vars", EVENT, "255", "Level"),
            "Vars.Level",
            "VARIABLE",
        ),
        (
            GrentonActionAttribute("clu", "CLU", EVENT, "true", "18", lua_value="true"),
            "CLU.18",
            "ATTRIBUTE",
        ),
    ],
)
def test_assignment_references_have_only_compact_prefixed_target_fields(
    action, target, call_type
):
    assert action_reference(action, "action_on_") == {
        "action_on_clu_id": "clu",
        "action_on_call_type": call_type,
        "action_on_object": target,
    }


@pytest.mark.parametrize(
    "value,args",
    [
        ('"cabinet",255', ["cabinet", 255]),
        ('"", false, nil, 1.25, 0', ["", False, None, 1.25, 0]),
        ('"a,b", "say \\"hello\\"", $value$', ["a,b", 'say "hello"', "$value$"]),
        (
            'OTHER:get(1, 2), {1, 2}, "a" .. "b"',
            ["OTHER:get(1, 2)", "{1, 2}", '"a" .. "b"'],
        ),
        ("", []),
        ("1, unfinished(", ["1, unfinished("]),
    ],
)
def test_script_keeps_target_and_plain_arguments_separate(value, args):
    action = GrentonActionScript("clu", "LEDSetValue", EVENT, value)
    assert action_reference(action) == {
        "clu_id": "clu",
        "call_type": "SCRIPT",
        "object": "LEDSetValue",
        "args": args,
    }


@pytest.mark.parametrize("value", ["", '"cabinet",255', "false", "  a,b  "])
def test_imported_method_has_one_string_argument_instead_of_inferred_script_args(value):
    action = GrentonActionMethod("clu", "Relay", EVENT, value, "3")
    metadata = action_reference(action)
    assert metadata["args"] == [value]
    assert metadata["call_type"] == "METHOD"
    assert metadata["object"] == "Relay.3"
    assert action.arguments is None and action.value == value


def test_configured_method_args_are_typed_and_fresh_without_exposing_editor_rows():
    action = GrentonActionMethod(
        "clu",
        "Relay",
        EVENT,
        "unused",
        "3",
        arguments=('"cabinet"', "255", "false", "nil", "$value$"),
    )
    expected = {
        "action_set_value_clu_id": "clu",
        "action_set_value_call_type": "METHOD",
        "action_set_value_object": "Relay.3",
        "action_set_value_args": ["cabinet", 255, False, None, "$value$"],
    }
    metadata = action_reference(action, "action_set_value_")
    assert metadata == expected
    metadata["action_set_value_args"].append("mutated")
    assert action_reference(action, "action_set_value_") == expected


def test_configured_method_without_arguments_preserves_empty_argument_list():
    action = GrentonActionMethod("clu", "Relay", EVENT, "ignored", "3", arguments=())
    assert action_reference(action) == {
        "clu_id": "clu",
        "call_type": "METHOD",
        "object": "Relay.3",
        "args": [],
    }
