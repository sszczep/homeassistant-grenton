"""Subscription destruction identifies only the requested report destination."""

import pytest

from custom_components.homeassistant_grenton.domain.api.clu_messages import (
    GrentonCluApiClientDestroyRequest,
    GrentonCluApiClientDestroyResponse,
    GrentonCluApiClientRegisterRequest,
)
from custom_components.homeassistant_grenton.state import GrentonCluStateAttributeKey


def test_register_preserves_existing_default_subscription_id():
    key = GrentonCluStateAttributeKey("CLU1", "0")
    request = GrentonCluApiClientRegisterRequest([key], 0, "1234abcd")
    assert request.raw == "req::1234abcd:SYSTEM:clientRegister(0,0,1,{{CLU1,0}})"


def test_register_supports_custom_id_without_changing_report_port():
    key = GrentonCluStateAttributeKey("CLU1", "0")
    request = GrentonCluApiClientRegisterRequest(
        [key], 0, "1234abcd", subscription_id=3456
    )
    assert request.raw == "req::1234abcd:SYSTEM:clientRegister(0,0,3456,{{CLU1,0}})"
    assert request.subscription_id == 3456


@pytest.mark.parametrize("subscription_id", [-1, True, 1.0, "69"])
def test_register_rejects_invalid_custom_subscription_id(subscription_id):
    key = GrentonCluStateAttributeKey("CLU1", "0")
    with pytest.raises(ValueError, match="Subscription ID"):
        GrentonCluApiClientRegisterRequest([key], 0, subscription_id=subscription_id)


def test_destroy_request_uses_source_address_and_port_by_default():
    request = GrentonCluApiClientDestroyRequest(69, "1234ABCD")
    assert request.raw == "req::1234abcd:SYSTEM:clientDestroy(0,0,69)"
    assert request.subscription_id == 69
    assert request.report_ip is None
    assert request.report_port == 0


def test_destroy_request_supports_explicit_report_destination():
    request = GrentonCluApiClientDestroyRequest(
        49064, report_ip="192.0.2.20", report_port=4344
    )
    assert request.payload == 'SYSTEM:clientDestroy("192.0.2.20",4344,49064)'
    assert request.report_ip == "192.0.2.20"
    assert request.report_port == 4344


@pytest.mark.parametrize("subscription_id", [-1, True, 1.0, "69", None])
def test_destroy_rejects_invalid_subscription_id(subscription_id):
    with pytest.raises(ValueError, match="Subscription ID"):
        GrentonCluApiClientDestroyRequest(subscription_id)
    with pytest.raises(ValueError, match="Subscription ID"):
        GrentonCluApiClientDestroyResponse("resp:192.0.2.1:1234abcd:69", subscription_id)


@pytest.mark.parametrize("report_port", [-1, 65536, False, 4344.0, "4344"])
def test_destroy_rejects_invalid_report_port(report_port):
    with pytest.raises(ValueError, match="Report port"):
        GrentonCluApiClientDestroyRequest(69, report_port=report_port)


@pytest.mark.parametrize(
    "report_ip", ["", "not-an-address", "::1", '1.2.3.4",1,2)', 1, True]
)
def test_destroy_rejects_invalid_report_address_without_lua_injection(report_ip):
    with pytest.raises(ValueError, match="Report address"):
        GrentonCluApiClientDestroyRequest(69, report_ip=report_ip)


def test_destroy_response_verifies_requested_subscription_id():
    response = GrentonCluApiClientDestroyResponse("resp:192.0.2.1:1234ABCD:69", 69)
    assert response.subscription_id == 69
    assert response.msg_id == "1234abcd"
    assert response.clu_ip == "192.0.2.1"


@pytest.mark.parametrize(
    "payload", ["", "nil", "true", "{69}", "clientReport:69:{}", "69.0", "-69", " 69"]
)
def test_destroy_response_rejects_non_numeric_acknowledgements(payload):
    with pytest.raises(ValueError, match="Invalid clientDestroy acknowledgement"):
        GrentonCluApiClientDestroyResponse(f"resp:192.0.2.1:1234abcd:{payload}", 69)


def test_destroy_response_rejects_other_subscription_id():
    with pytest.raises(ValueError, match="Unexpected clientDestroy subscription ID"):
        GrentonCluApiClientDestroyResponse("resp:192.0.2.1:1234abcd:70", 69)


@pytest.mark.parametrize(
    "wire", ["private-state", "resp:::private-state", "resp:192.0.2.1:private-state"]
)
def test_invalid_destroy_envelope_does_not_expose_private_packet_contents(wire):
    with pytest.raises(ValueError) as error:
        GrentonCluApiClientDestroyResponse(wire, 69)
    assert str(error.value) == "Invalid clientDestroy response envelope"
    assert "private-state" not in str(error.value)
