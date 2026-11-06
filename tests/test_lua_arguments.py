"""Regression checks for importing individual argument controls safely."""

import pytest

from custom_components.homeassistant_grenton.domain.lua_arguments import (
    imported_lua_argument,
    split_lua_arguments,
)
from custom_components.homeassistant_grenton.domain.scene_arguments import (
    imported_arguments,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('42, "abc", true, nil', ["42", '"abc"', "true", "nil"]),
        ('"a,b", OTHER:get(1, 2), {1, 2}', ['"a,b"', "OTHER:get(1, 2)", "{1, 2}"]),
        (r'"a\",b", "c"', [r'"a\",b"', '"c"']),
        ('[=[a,b]=], state["a,b"]', ["[=[a,b]=]", 'state["a,b"]']),
        ("", []),
        ("1, function(a,b) return a,b end", ["1, function(a,b) return a,b end"]),
        ("1 -- comment, next\n, 2", ["1 -- comment, next\n, 2"]),
        ("1, unfinished(", ["1, unfinished("]),
        ('1, "unfinished', ['1, "unfinished']),
        ("1, ", ["1, "]),
    ],
)
def test_top_level_arguments_are_split_without_changing_nested_lua(value, expected):
    assert split_lua_arguments(value) == expected


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ('"abc"', {"type": "string", "value": "abc"}),
        (r"'it\'s'", {"type": "string", "value": "it's"}),
        (r'"a\n\0279"', {"type": "string", "value": "a\n\x1b9"}),
        ("-1.25e2", {"type": "float", "value": -125.0}),
        ("1.0", {"type": "float", "value": 1.0}),
        ("9007199254740993", {"type": "number", "value": 9007199254740993}),
        ("false", {"type": "boolean", "value": False}),
        ("nil", {"type": "nil", "value": None}),
        ('"a" .. "b"', {"type": "lua", "value": '"a" .. "b"'}),
        (r'"\unknown"', {"type": "lua", "value": r'"\unknown"'}),
        ("OTHER:get(1, 2)", {"type": "lua", "value": "OTHER:get(1, 2)"}),
    ],
)
def test_literals_become_typed_controls_and_expressions_remain_lua(
    expression, expected
):
    assert imported_lua_argument(expression) == expected


@pytest.mark.parametrize("call_type", ["SCRIPT", "METHOD"])
def test_imported_scene_has_one_row_per_argument(call_type):
    assert imported_arguments(call_type, '0, "bedroom", false, nil') == [
        {"type": "number", "value": 0},
        {"type": "string", "value": "bedroom"},
        {"type": "boolean", "value": False},
        {"type": "nil", "value": None},
    ]


@pytest.mark.parametrize("call_type", ["SCRIPT", "METHOD"])
@pytest.mark.parametrize(
    "value, expected",
    [
        ("800,0", [{"type": "number", "value": 800}, {"type": "number", "value": 0}]),
        ('"800,0"', [{"type": "string", "value": "800,0"}]),
        (
            '800, OTHER:get(1, 2), "a,b", -0.5, true, nil',
            [
                {"type": "number", "value": 800},
                {"type": "lua", "value": "OTHER:get(1, 2)"},
                {"type": "string", "value": "a,b"},
                {"type": "float", "value": -0.5},
                {"type": "boolean", "value": True},
                {"type": "nil", "value": None},
            ],
        ),
        ("", []),
        ("800, unfinished(", [{"type": "lua", "value": "800, unfinished("}]),
    ],
)
def test_method_and_script_argument_import_uses_the_same_lua_parser(
    call_type, value, expected
):
    assert imported_arguments(call_type, value) == expected
