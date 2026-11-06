"""The CLI and integration share one count-aware report parser."""

import pytest

from custom_components.homeassistant_grenton.domain.api.clu_messages.client_register import (
    GrentonCluApiClientRegisterResponse,
)
from custom_components.homeassistant_grenton.state import GrentonCluStateVariableKey


@pytest.mark.parametrize(
    "content, expected",
    [
        ('1,"room, lamp",0', [1, "room, lamp", 0]),
        ('1,"room "left,right" label",0', [1, 'room "left,right" label', 0]),
        ('"room "left,right" label",0', ['room "left,right" label', 0]),
        ('1,"room \\"left,right\\" label",0', [1, 'room \\"left,right\\" label', 0]),
        ('nil,true,"  text  "', [None, True, "  text  "]),
    ],
)
def test_shared_report_parser_preserves_values_and_embedded_commas(content, expected):
    keys = [GrentonCluStateVariableKey(str(i)) for i in range(len(expected))]
    assert (
        GrentonCluApiClientRegisterResponse(
            f"resp:192.0.2.1:abcd:clientReport:0:{{{content}}}", keys
        ).values
        == expected
    )


@pytest.mark.parametrize(
    "content,count", [("1,2,3", 2), ("1", 2), ('"a","b","c"', 2), ('"a","b"', 1)]
)
def test_report_parser_never_merges_normal_values_to_hide_wrong_lengths(content, count):
    keys = [GrentonCluStateVariableKey(str(i)) for i in range(count)]
    with pytest.raises(ValueError):
        GrentonCluApiClientRegisterResponse(
            f"resp:192.0.2.1:abcd:clientReport:0:{{{content}}}", keys
        )
