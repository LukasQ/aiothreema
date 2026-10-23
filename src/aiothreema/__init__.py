"""Async Python client for the Threema Gateway HTTP API."""

from .client import ThreemaGatewayClient
from .exceptions import (
    ThreemaAuthError,
    ThreemaConnectionError,
    ThreemaGatewayError,
    ThreemaNoCreditsError,
    ThreemaRateLimitError,
    ThreemaSendError,
)
from .keys import derive_public_key, generate_key_pair
from .qr import generate_qr_code, qr_code_payload

__all__ = [
    "ThreemaAuthError",
    "ThreemaConnectionError",
    "ThreemaGatewayClient",
    "ThreemaGatewayError",
    "ThreemaNoCreditsError",
    "ThreemaRateLimitError",
    "ThreemaSendError",
    "derive_public_key",
    "generate_key_pair",
    "generate_qr_code",
    "qr_code_payload",
]

__version__ = "0.3.0"
