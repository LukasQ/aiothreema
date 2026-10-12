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
]

__version__ = "0.2.0"
