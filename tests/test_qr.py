"""Unit tests for Threema ID QR codes."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import segno

from aiothreema import (
    ThreemaGatewayClient,
    derive_public_key,
    generate_key_pair,
    generate_qr_code,
    qr_code_payload,
)

GATEWAY_ID = "*TESTGWY"
PUBLIC_KEY = "0123456789abcdef" * 4


def test_payload() -> None:
    """Test the QR code content follows the 3mid format."""
    assert qr_code_payload(GATEWAY_ID, PUBLIC_KEY) == f"3mid:*TESTGWY,{PUBLIC_KEY}"


def test_payload_lowercases_public_key() -> None:
    """Test the public key is normalized to lowercase hex."""
    assert qr_code_payload("ABCD1234", PUBLIC_KEY.upper()).endswith(PUBLIC_KEY)


@pytest.mark.parametrize(
    "threema_id",
    ["", "*TESTGW", "*TESTGWYX", "*testgwy", "AB*D1234", "*TEST GW"],
)
def test_payload_rejects_invalid_id(threema_id: str) -> None:
    """Test malformed Threema IDs are rejected."""
    with pytest.raises(ValueError, match="Threema ID"):
        qr_code_payload(threema_id, PUBLIC_KEY)


@pytest.mark.parametrize(
    "public_key",
    ["", PUBLIC_KEY[:-2], PUBLIC_KEY + "00", "zz" + PUBLIC_KEY[2:]],
)
def test_payload_rejects_invalid_public_key(public_key: str) -> None:
    """Test malformed public keys are rejected."""
    with pytest.raises(ValueError, match="Public key"):
        qr_code_payload(GATEWAY_ID, public_key)


def test_generate_svg() -> None:
    """Test the QR code is rendered as SVG by default and encodes the payload."""
    with patch("aiothreema.qr.segno.make", wraps=segno.make) as mock_make:
        image = generate_qr_code(GATEWAY_ID, PUBLIC_KEY)
    mock_make.assert_called_once_with(f"3mid:*TESTGWY,{PUBLIC_KEY}", micro=False)
    assert image.startswith(b"<?xml")
    assert b"<svg" in image


def test_generate_png() -> None:
    """Test the QR code can be rendered as PNG."""
    image = generate_qr_code(GATEWAY_ID, PUBLIC_KEY, kind="png")
    assert image.startswith(b"\x89PNG\r\n\x1a\n")


def test_generate_scale() -> None:
    """Test a larger scale produces a larger image."""
    small = generate_qr_code(GATEWAY_ID, PUBLIC_KEY, kind="png", scale=1)
    large = generate_qr_code(GATEWAY_ID, PUBLIC_KEY, kind="png", scale=10)
    assert len(large) > len(small)


def test_generate_rejects_invalid_input() -> None:
    """Test rendering validates its input."""
    with pytest.raises(ValueError):
        generate_qr_code("nope", PUBLIC_KEY)


def test_client_public_key() -> None:
    """Test the client derives its public key from the private key."""
    private_key, public_key = generate_key_pair()
    client = ThreemaGatewayClient(GATEWAY_ID, "secret", private_key=private_key)
    assert client.public_key == public_key == derive_public_key(private_key)


def test_client_public_key_without_private_key() -> None:
    """Test the client has no public key in simple mode."""
    assert ThreemaGatewayClient(GATEWAY_ID, "secret").public_key is None
