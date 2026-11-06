"""Anonymized Object Manager schedule reads preserve their unframed scalar body."""

import pytest
from test_clu_state import make_clu

from custom_components.homeassistant_grenton.domain.api.clu_messages import (
    GrentonCluApiGetValueRequest,
    GrentonCluApiGetValueResponse,
)
from custom_components.homeassistant_grenton.domain.thermostat_schedule import (
    decode_schedule,
)
from custom_components.homeassistant_grenton.state import (
    GrentonCluStateAttributeKey,
    GrentonCluStateVariableKey,
)


def test_direct_request_matches_captured_object_manager_schedule_read():
    key = GrentonCluStateAttributeKey("THERMOSTAT1", "9")
    request = GrentonCluApiGetValueRequest(key, "1234ABCD")
    assert request.raw == "req::1234abcd:THERMOSTAT1:get(9)"
    assert request.key is key
    assert request.keys == [key]
    assert GrentonCluApiGetValueRequest(key).msg_id != request.msg_id


@pytest.mark.parametrize(
    "object_name,index",
    [
        ("", "9"),
        ("THERMOSTAT1;Other()", "9"),
        ("THERMOSTAT1", "9);Other()"),
        ("THERMOSTAT1", "-1"),
        ("THERMOSTAT1", "9.0"),
        ("THERMOSTAT1", "٩"),
        ("THERMOSTAT1", 9),
    ],
)
def test_direct_request_rejects_expressions_in_attribute_target(object_name, index):
    with pytest.raises(ValueError):
        GrentonCluApiGetValueRequest(GrentonCluStateAttributeKey(object_name, index))


def test_variable_reads_need_a_separate_verified_protocol_operation():
    with pytest.raises(TypeError, match="attribute key"):
        GrentonCluApiGetValueRequest(GrentonCluStateVariableKey("Schedule"))


@pytest.mark.parametrize(
    "payload,expected",
    [
        ("nil", None),
        ("true", True),
        ("false", False),
        ("0", 0),
        ("00123", 123),
        ("-22.5", -22.5),
        (".5", 0.5),
        ("2.5e2", 250.0),
        ("", ""),
        ("NIL", "NIL"),
        (" true ", " true "),
        ('"22.5"', '"22.5"'),
        ('"nil"', '"nil"'),
        ('  room "left,right" label  ', '  room "left,right" label  '),
        ("{a,b}:value", "{a,b}:value"),
        ("values:{1,2}", "values:{1,2}"),
        ('\\n\\"quoted\\"', '\\n\\"quoted\\"'),
    ],
)
def test_direct_reply_parses_only_exact_primitives_and_preserves_other_text(
    payload, expected
):
    key = GrentonCluStateAttributeKey("THERMOSTAT1", "9")
    response = GrentonCluApiGetValueResponse(f"resp:192.0.2.1:1234abcd:{payload}", key)
    assert response.values == [expected]


def test_full_schedule_round_trip_uses_raw_body_and_preserves_trailing_space():
    # A trailer factor can use the space digit. It must not be trimmed even
    # though the captured get(9) scalar has no surrounding quotes or braces.
    payload = "Y0" * 672 + "+00:3 "
    assert len(payload) == 1350
    key = GrentonCluStateAttributeKey("THERMOSTAT1", "9")
    response = GrentonCluApiGetValueResponse(f"resp:192.0.2.1:1234abcd:{payload}", key)
    assert response.values == [payload]
    # The standard captured sample still decodes through the existing codec.
    standard = GrentonCluApiGetValueResponse(
        "resp:192.0.2.1:1234abcd:" + "Y0" * 672 + "+00:30", key
    )
    assert set(decode_schedule(standard.values[0], 30).temperatures) == {20}


@pytest.mark.parametrize("payload", ["1.20", "00123", "05.15.24-2635", " true "])
def test_direct_firmware_reply_preserves_identifier(payload):
    clu = make_clu("clu1")
    key = GrentonCluStateAttributeKey(clu.object_name, "17")
    response = GrentonCluApiGetValueResponse(
        f"resp:192.0.2.1:1234abcd:{payload}", key, clu
    )
    assert response.values == [payload]


@pytest.mark.parametrize(
    "wire", ["req::id:private-value", "resp:::private-value", "resp:bad"]
)
def test_invalid_direct_envelope_does_not_expose_value(wire):
    key = GrentonCluStateAttributeKey("THERMOSTAT1", "9")
    with pytest.raises(
        ValueError, match="Invalid direct attribute response envelope"
    ) as error:
        GrentonCluApiGetValueResponse(wire, key)
    assert "private-value" not in str(error.value)
