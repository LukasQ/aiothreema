"""Exceptions raised by the Threema Gateway client."""

from __future__ import annotations


class ThreemaGatewayError(Exception):
    """Base class for all errors raised by this library."""


class ThreemaConnectionError(ThreemaGatewayError):
    """Raised for network or transport failures talking to the Gateway."""


class ThreemaAuthError(ThreemaGatewayError):
    """Raised when the Gateway ID or API secret is rejected (HTTP 401)."""


class ThreemaSendError(ThreemaGatewayError):
    """Raised when sending a message or resolving a recipient key fails."""


class ThreemaNoCreditsError(ThreemaSendError):
    """Raised when the Gateway account is out of credits (HTTP 402)."""


# Inherits from both so that callers catching either of the errors documented
# for validate_credentials() / send_text_message() keep catching rate limits.
class ThreemaRateLimitError(ThreemaSendError, ThreemaConnectionError):
    """Raised when the Gateway keeps rejecting requests with HTTP 429.

    `retry_after` holds the delay in seconds requested by the Gateway via the
    Retry-After header, or None if it didn't send one.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        """Initialize the rate limit error."""
        super().__init__(message)
        self.retry_after = retry_after
