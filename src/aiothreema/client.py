"""Async client for the Threema Gateway HTTP API."""

from __future__ import annotations

import itertools
import logging
import os
import random
from asyncio import sleep
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType

import aiohttp
import nacl.public
import nacl.utils

from ._ratelimit import RateLimiter
from .exceptions import (
    ThreemaAuthError,
    ThreemaConnectionError,
    ThreemaNoCreditsError,
    ThreemaRateLimitError,
    ThreemaSendError,
)

_LOGGER = logging.getLogger(__name__)

_BASE_URL = "https://msgapi.threema.ch"
_HTTP_BAD_REQUEST = 400
_HTTP_UNAUTHORIZED = 401
_HTTP_PAYMENT_REQUIRED = 402
_HTTP_TOO_MANY_REQUESTS = 429
_RETRY_STATUSES = frozenset({500, 502, 503, 504})
_RETRY_BASE_DELAY = 1.0
_MAX_RETRY_DELAY = 30.0
_MSG_TYPE_TEXT = 0x01


def _backoff_delay(attempt: int) -> float:
    """Return an exponential backoff delay with jitter for a 0-based attempt."""
    delay = min(_MAX_RETRY_DELAY, _RETRY_BASE_DELAY * 2**attempt)
    return delay / 2 + random.uniform(0, delay / 2)


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header (delay in seconds or HTTP date) into seconds."""
    if not value:
        return None
    try:
        return float(max(0, int(value)))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


class ThreemaGatewayClient:
    """Client for sending messages via the Threema Gateway.

    Accepts an externally managed `aiohttp.ClientSession` (recommended when
    embedding this client in a larger application), or none at all, in which
    case the client creates and owns its own session — use it as an async
    context manager in that case::

        async with ThreemaGatewayClient(gateway_id, api_secret) as client:
            await client.send_text_message("ABCD1234", "Hello!")

    Requests are throttled client-side to `rate_limit` requests per second
    (None disables throttling), and transient failures are retried up to
    `max_retries` times with exponential backoff (0 disables retries). A
    message send is only retried when the Gateway definitely did not accept
    it, so a retry never delivers a message twice.
    """

    def __init__(
        self,
        gateway_id: str,
        api_secret: str,
        private_key: str | None = None,
        *,
        session: aiohttp.ClientSession | None = None,
        max_retries: int = 3,
        rate_limit: int | None = 10,
    ) -> None:
        """Initialize the Threema Gateway client."""
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        self.gateway_id = gateway_id
        self.api_secret = api_secret
        self.private_key = private_key
        self._session = session
        self._owns_session = session is None
        self._max_retries = max_retries
        self._rate_limiter = RateLimiter(rate_limit) if rate_limit is not None else None

    async def __aenter__(self) -> ThreemaGatewayClient:
        """Create an owned session, if one wasn't supplied."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the session, if this client owns it."""
        if self._owns_session and self._session is not None:
            await self._session.close()

    @property
    def _client_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError(
                "No aiohttp session available. Either pass one to the "
                "constructor, or use this client as an async context manager."
            )
        return self._session

    async def _request(
        self, method: str, path: str, **kwargs: object
    ) -> tuple[int, str]:
        """Send a rate-limited request, retrying transient failures.

        Returns (status, body) of the final response.
        Raises ThreemaAuthError for HTTP 401 and ThreemaRateLimitError if the
        Gateway keeps answering with HTTP 429. Connection errors are re-raised
        once the retries are exhausted.
        """
        request = getattr(self._client_session, method)
        url = f"{_BASE_URL}{path}"
        # A POST may have been processed even if we never saw the response, so
        # it is only retried when the Gateway definitely did not accept it.
        idempotent = method == "get"

        for attempt in itertools.count():
            can_retry = attempt < self._max_retries
            if self._rate_limiter is not None:
                await self._rate_limiter.acquire()

            try:
                resp = await request(url, **kwargs)
            except (aiohttp.ClientError, TimeoutError) as err:
                # ClientConnectorError: the connection was never established.
                safe = idempotent or isinstance(err, aiohttp.ClientConnectorError)
                if not (safe and can_retry):
                    raise
                delay = _backoff_delay(attempt)
                reason = repr(err)
            else:
                status = resp.status
                reason = f"HTTP {status}"
                if status == _HTTP_UNAUTHORIZED:
                    resp.release()
                    raise ThreemaAuthError("Invalid Threema Gateway credentials")
                if status == _HTTP_TOO_MANY_REQUESTS:
                    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                    resp.release()
                    delay = (
                        retry_after
                        if retry_after is not None
                        else _backoff_delay(attempt)
                    )
                    if not can_retry or delay > _MAX_RETRY_DELAY:
                        raise ThreemaRateLimitError(
                            "Threema Gateway rate limit exceeded",
                            retry_after=retry_after,
                        )
                    if self._rate_limiter is not None:
                        self._rate_limiter.pause(delay)
                elif idempotent and can_retry and status in _RETRY_STATUSES:
                    resp.release()
                    delay = _backoff_delay(attempt)
                else:
                    try:
                        return status, await resp.text()
                    except (aiohttp.ClientError, TimeoutError) as err:
                        if not (idempotent and can_retry):
                            raise
                        delay = _backoff_delay(attempt)
                        reason = repr(err)

            _LOGGER.debug(
                "Request to %s failed (%s), retry %d/%d in %.1fs",
                path,
                reason,
                attempt + 1,
                self._max_retries,
                delay,
            )
            await sleep(delay)

        raise AssertionError("unreachable")

    async def get_credits(self) -> int:
        """Return the number of credits remaining on the Gateway account.

        Raises ThreemaAuthError for invalid credentials.
        Raises ThreemaConnectionError for other failures.
        """
        try:
            status, body = await self._request(
                "get",
                "/credits",
                params={"from": self.gateway_id, "secret": self.api_secret},
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ThreemaConnectionError(
                f"Connection error fetching credits: {err}"
            ) from err

        if status >= _HTTP_BAD_REQUEST:
            raise ThreemaConnectionError(
                f"Gateway error fetching credits: HTTP {status}"
            )
        try:
            return int(body.strip())
        except ValueError as err:
            raise ThreemaConnectionError(
                f"Malformed credits response from Gateway: {body!r}"
            ) from err

    async def validate_credentials(self) -> None:
        """Validate the Gateway credentials by checking remaining credits.

        Raises ThreemaAuthError for invalid credentials.
        Raises ThreemaConnectionError for other failures.
        """
        remaining_credits = await self.get_credits()
        _LOGGER.debug("Gateway credentials validated, credits: %d", remaining_credits)

    async def _fetch_recipient_public_key(
        self, recipient_id: str
    ) -> nacl.public.PublicKey:
        """Fetch recipient public key from Threema Gateway."""
        try:
            status, key_hex = await self._request(
                "get",
                f"/pubkeys/{recipient_id}",
                params={"from": self.gateway_id, "secret": self.api_secret},
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ThreemaSendError(
                f"Failed to fetch public key for {recipient_id}: {err}"
            ) from err

        if status >= _HTTP_BAD_REQUEST:
            raise ThreemaSendError(
                f"Failed to fetch public key for {recipient_id}: HTTP {status}"
            )

        try:
            return nacl.public.PublicKey(bytes.fromhex(key_hex.strip()))
        except ValueError as err:
            raise ThreemaSendError(
                f"Malformed public key received for {recipient_id}: {err}"
            ) from err

    def _build_encrypted_message(
        self, text: str, recipient_public_key: nacl.public.PublicKey
    ) -> tuple[bytes, bytes]:
        """Build and encrypt a text message for E2E delivery.

        Returns (nonce, ciphertext) as raw bytes.
        """
        assert self.private_key is not None
        text_bytes = text.encode("utf-8")
        padding_length = os.urandom(1)[0] or 255
        padding = bytes([padding_length] * padding_length)
        plaintext = bytes([_MSG_TYPE_TEXT]) + text_bytes + padding

        private_key = nacl.public.PrivateKey(bytes.fromhex(self.private_key))
        nonce = nacl.utils.random(nacl.public.Box.NONCE_SIZE)
        box = nacl.public.Box(private_key, recipient_public_key)
        encrypted = box.encrypt(plaintext, nonce)
        return encrypted.nonce, encrypted.ciphertext

    async def send_text_message(self, recipient_id: str, text: str) -> str:
        """Send a text message to a Threema ID.

        Sends end-to-end encrypted if a private key was configured,
        otherwise sends via simple (non-E2E) mode.

        Returns the message ID on success.
        Raises ThreemaSendError on failure, or one of its subclasses:
        ThreemaNoCreditsError if the account is out of credits, and
        ThreemaRateLimitError if the Gateway's rate limit was hit.
        """
        try:
            if self.private_key:
                _LOGGER.debug("Sending E2E encrypted message to %s", recipient_id)
                recipient_pub_key = await self._fetch_recipient_public_key(recipient_id)
                nonce, ciphertext = self._build_encrypted_message(
                    text, recipient_pub_key
                )
                status, message_id = await self._request(
                    "post",
                    "/send_e2e",
                    data={
                        "from": self.gateway_id,
                        "to": recipient_id,
                        "secret": self.api_secret,
                        "nonce": nonce.hex(),
                        "box": ciphertext.hex(),
                    },
                )
            else:
                _LOGGER.debug("Sending simple message to %s", recipient_id)
                status, message_id = await self._request(
                    "post",
                    "/send_simple",
                    data={
                        "from": self.gateway_id,
                        "to": recipient_id,
                        "secret": self.api_secret,
                        "text": text,
                    },
                )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ThreemaSendError(
                f"Connection error sending message to {recipient_id}: {err}"
            ) from err

        if status == _HTTP_PAYMENT_REQUIRED:
            raise ThreemaNoCreditsError(
                f"Cannot send message to {recipient_id}: no credits remaining"
            )
        if status >= _HTTP_BAD_REQUEST:
            raise ThreemaSendError(
                f"Gateway error sending message to {recipient_id}: HTTP {status}"
            )

        _LOGGER.debug("Message sent to %s (ID: %s)", recipient_id, message_id)
        return message_id
