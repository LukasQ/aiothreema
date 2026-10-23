"""Threema ID QR codes for verifying a Gateway's public key."""

from __future__ import annotations

import io
import re
from typing import Literal

import segno

_THREEMA_ID = re.compile(r"[A-Z0-9*][A-Z0-9]{7}")
_PUBLIC_KEY = re.compile(r"[0-9a-fA-F]{64}")


def qr_code_payload(threema_id: str, public_key: str) -> str:
    """Return the content of the Threema ID QR code (`3mid:<id>,<public key>`).

    Scanning it in the Threema app verifies the ID's public key.
    Raises ValueError for a malformed Threema ID or public key.
    """
    if not _THREEMA_ID.fullmatch(threema_id):
        raise ValueError(f"Invalid Threema ID: {threema_id!r}")
    if not _PUBLIC_KEY.fullmatch(public_key):
        raise ValueError("Public key must be 64 hex characters")
    return f"3mid:{threema_id},{public_key.lower()}"


def generate_qr_code(
    threema_id: str,
    public_key: str,
    *,
    kind: Literal["svg", "png"] = "svg",
    scale: int = 5,
) -> bytes:
    """Render the Threema ID QR code as an SVG or PNG image.

    `scale` is the size of a single module in pixels. The code is CPU-bound,
    so run it in an executor when calling it from an event loop.
    Raises ValueError for a malformed Threema ID or public key.
    """
    qr_code = segno.make(qr_code_payload(threema_id, public_key), micro=False)
    buffer = io.BytesIO()
    qr_code.save(buffer, kind=kind, scale=scale, dark="#000", light="#fff")
    return buffer.getvalue()
