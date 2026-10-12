"""Unit tests for ThreemaGatewayClient."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import nacl.public
import pytest

from aiothreema import (
    ThreemaAuthError,
    ThreemaConnectionError,
    ThreemaGatewayClient,
    ThreemaNoCreditsError,
    ThreemaRateLimitError,
    ThreemaSendError,
)
from aiothreema.client import _parse_retry_after

MOCK_GATEWAY_ID = "*TESTGWY"
MOCK_API_SECRET = "test_secret_key_12345"


@pytest.fixture(autouse=True)
def mock_sleep(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Skip the retry backoff delays."""
    sleep = AsyncMock()
    monkeypatch.setattr("aiothreema.client.sleep", sleep)
    return sleep


def _make_resp(
    status: int = 200, text: str = "OK", headers: dict[str, str] | None = None
) -> MagicMock:
    """Create a mock aiohttp response."""
    resp = MagicMock()
    resp.status = status
    resp.ok = status < 400
    resp.headers = headers or {}
    resp.text = AsyncMock(return_value=text)
    return resp


def _make_session(
    get_resp: MagicMock | None = None,
    post_resp: MagicMock | None = None,
) -> MagicMock:
    """Create a mock aiohttp client session."""
    session = MagicMock()
    session.get = AsyncMock(return_value=get_resp)
    session.post = AsyncMock(return_value=post_resp)
    return session


# ── validate_credentials ─────────────────────────────────────────────────


async def test_validate_credentials_success() -> None:
    """Test successful credential validation."""
    session = _make_session(get_resp=_make_resp(200, "100"))
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    await client.validate_credentials()
    session.get.assert_awaited_once_with(
        "https://msgapi.threema.ch/credits",
        params={"from": MOCK_GATEWAY_ID, "secret": MOCK_API_SECRET},
    )


async def test_validate_credentials_auth_error() -> None:
    """Test that 401 raises ThreemaAuthError."""
    session = _make_session(get_resp=_make_resp(401))
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaAuthError):
        await client.validate_credentials()


async def test_validate_credentials_server_error() -> None:
    """Test that non-401 HTTP error raises ThreemaConnectionError."""
    session = _make_session(get_resp=_make_resp(500))
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaConnectionError):
        await client.validate_credentials()


@pytest.mark.parametrize(
    "side_effect",
    [aiohttp.ClientError("connection reset"), TimeoutError()],
    ids=["client_error", "timeout"],
)
async def test_validate_credentials_connection_error(side_effect: Exception) -> None:
    """Test that a connection error or timeout raises ThreemaConnectionError."""
    session = MagicMock()
    session.get = AsyncMock(side_effect=side_effect)
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaConnectionError):
        await client.validate_credentials()


@pytest.mark.parametrize(
    "side_effect",
    [aiohttp.ClientPayloadError("connection dropped"), TimeoutError()],
    ids=["payload_error", "timeout"],
)
async def test_validate_credentials_read_error(side_effect: Exception) -> None:
    """Test a failure reading the validation response raises ThreemaConnectionError."""
    resp = _make_resp(200)
    resp.text = AsyncMock(side_effect=side_effect)
    session = _make_session(get_resp=resp)
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaConnectionError):
        await client.validate_credentials()


# ── get_credits ──────────────────────────────────────────────────────────


async def test_get_credits_success() -> None:
    """Test the remaining credits are returned as an int."""
    session = _make_session(get_resp=_make_resp(200, "1234\n"))
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    assert await client.get_credits() == 1234
    session.get.assert_awaited_once_with(
        "https://msgapi.threema.ch/credits",
        params={"from": MOCK_GATEWAY_ID, "secret": MOCK_API_SECRET},
    )


async def test_get_credits_auth_error() -> None:
    """Test that 401 raises ThreemaAuthError."""
    session = _make_session(get_resp=_make_resp(401))
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaAuthError):
        await client.get_credits()


async def test_get_credits_malformed_response() -> None:
    """Test a non-numeric credits response raises ThreemaConnectionError."""
    session = _make_session(get_resp=_make_resp(200, "<html>oops</html>"))
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaConnectionError):
        await client.get_credits()


# ── send_text_message: simple mode ───────────────────────────────────────


async def test_send_simple_success() -> None:
    """Test successful simple message send."""
    session = _make_session(post_resp=_make_resp(200, "msg123"))
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    message_id = await client.send_text_message("ABCD1234", "Hello!")
    assert message_id == "msg123"
    session.post.assert_awaited_once_with(
        "https://msgapi.threema.ch/send_simple",
        data={
            "from": MOCK_GATEWAY_ID,
            "to": "ABCD1234",
            "secret": MOCK_API_SECRET,
            "text": "Hello!",
        },
    )


async def test_send_simple_auth_error() -> None:
    """Test that 401 during simple send raises ThreemaAuthError."""
    session = _make_session(post_resp=_make_resp(401))
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaAuthError):
        await client.send_text_message("ABCD1234", "Hello!")


async def test_send_simple_no_credits() -> None:
    """Test that 402 during simple send raises ThreemaNoCreditsError, unretried."""
    session = _make_session(post_resp=_make_resp(402))
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaNoCreditsError) as exc_info:
        await client.send_text_message("ABCD1234", "Hello!")
    assert isinstance(exc_info.value, ThreemaSendError)
    session.post.assert_awaited_once()


async def test_send_e2e_no_credits() -> None:
    """Test that 402 during E2E send raises ThreemaNoCreditsError."""
    sender_hex, recipient_priv = _e2e_keys()
    session = MagicMock()
    session.get = AsyncMock(
        return_value=_make_resp(200, bytes(recipient_priv.public_key).hex())
    )
    session.post = AsyncMock(return_value=_make_resp(402))
    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, private_key=sender_hex, session=session
    )
    with pytest.raises(ThreemaNoCreditsError):
        await client.send_text_message("ABCD1234", "Hello E2E!")


async def test_send_simple_server_error() -> None:
    """Test that non-401 HTTP error during simple send raises ThreemaSendError."""
    session = _make_session(post_resp=_make_resp(500))
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaSendError):
        await client.send_text_message("ABCD1234", "Hello!")


@pytest.mark.parametrize(
    "side_effect",
    [aiohttp.ClientError("connection reset"), TimeoutError()],
    ids=["client_error", "timeout"],
)
async def test_send_simple_connection_error(side_effect: Exception) -> None:
    """Test a connection error or timeout during simple send raises ThreemaSendError."""
    session = MagicMock()
    session.post = AsyncMock(side_effect=side_effect)
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaSendError):
        await client.send_text_message("ABCD1234", "Hello!")


@pytest.mark.parametrize(
    "side_effect",
    [aiohttp.ClientPayloadError("connection dropped"), TimeoutError()],
    ids=["payload_error", "timeout"],
)
async def test_send_simple_read_error(side_effect: Exception) -> None:
    """Test a failure reading the send response raises ThreemaSendError."""
    resp = _make_resp(200)
    resp.text = AsyncMock(side_effect=side_effect)
    session = _make_session(post_resp=resp)
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaSendError):
        await client.send_text_message("ABCD1234", "Hello!")


# ── send_text_message: E2E mode ──────────────────────────────────────────


def _e2e_keys() -> tuple[str, nacl.public.PrivateKey]:
    """Return (sender_private_hex, recipient_private_key) for E2E tests."""
    sender = nacl.public.PrivateKey.generate()
    recipient = nacl.public.PrivateKey.generate()
    return bytes(sender).hex(), recipient


async def test_send_e2e_success() -> None:
    """Test a successful E2E encrypted message send round-trips correctly."""
    sender_hex, recipient_priv = _e2e_keys()
    pub_hex = bytes(recipient_priv.public_key).hex()

    session = MagicMock()
    session.get = AsyncMock(return_value=_make_resp(200, pub_hex))
    session.post = AsyncMock(return_value=_make_resp(200, "msg456"))

    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, private_key=sender_hex, session=session
    )
    message_id = await client.send_text_message("ABCD1234", "Hello E2E!")

    assert message_id == "msg456"
    session.get.assert_awaited_once()
    session.post.assert_awaited_once()

    # Decrypt the posted payload and verify it round-trips to the original text.
    _, kwargs = session.post.call_args
    nonce = bytes.fromhex(kwargs["data"]["nonce"])
    box_bytes = bytes.fromhex(kwargs["data"]["box"])
    sender_pub = nacl.public.PrivateKey(bytes.fromhex(sender_hex)).public_key
    decrypt_box = nacl.public.Box(recipient_priv, sender_pub)
    plaintext = decrypt_box.decrypt(box_bytes, nonce)

    msg_type = plaintext[0]
    assert msg_type == 0x01
    padding_length = plaintext[-1]
    text_bytes = plaintext[1:-padding_length]
    assert text_bytes.decode("utf-8") == "Hello E2E!"


async def test_send_e2e_pubkey_not_found() -> None:
    """Test that a 404 fetching pubkey raises ThreemaSendError."""
    sender_hex, _ = _e2e_keys()
    session = MagicMock()
    session.get = AsyncMock(return_value=_make_resp(404))

    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, private_key=sender_hex, session=session
    )
    with pytest.raises(ThreemaSendError):
        await client.send_text_message("ABCD1234", "Hello E2E!")


async def test_send_e2e_pubkey_auth_error() -> None:
    """Test that 401 fetching pubkey raises ThreemaAuthError."""
    sender_hex, _ = _e2e_keys()
    session = MagicMock()
    session.get = AsyncMock(return_value=_make_resp(401))

    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, private_key=sender_hex, session=session
    )
    with pytest.raises(ThreemaAuthError):
        await client.send_text_message("ABCD1234", "Hello E2E!")


async def test_send_e2e_pubkey_malformed() -> None:
    """Test that a malformed pubkey response raises ThreemaSendError."""
    sender_hex, _ = _e2e_keys()
    session = MagicMock()
    session.get = AsyncMock(return_value=_make_resp(200, "not-hex-and-wrong-length"))

    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, private_key=sender_hex, session=session
    )
    with pytest.raises(ThreemaSendError):
        await client.send_text_message("ABCD1234", "Hello E2E!")


@pytest.mark.parametrize(
    "side_effect",
    [aiohttp.ClientError("connection reset"), TimeoutError()],
    ids=["client_error", "timeout"],
)
async def test_send_e2e_pubkey_connection_error(side_effect: Exception) -> None:
    """Test a connection error or timeout fetching pubkey raises ThreemaSendError."""
    sender_hex, _ = _e2e_keys()
    session = MagicMock()
    session.get = AsyncMock(side_effect=side_effect)

    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, private_key=sender_hex, session=session
    )
    with pytest.raises(ThreemaSendError):
        await client.send_text_message("ABCD1234", "Hello E2E!")


@pytest.mark.parametrize(
    "side_effect",
    [aiohttp.ClientPayloadError("connection dropped"), TimeoutError()],
    ids=["payload_error", "timeout"],
)
async def test_send_e2e_pubkey_read_error(side_effect: Exception) -> None:
    """Test a failure reading the pubkey response raises ThreemaSendError."""
    sender_hex, _ = _e2e_keys()
    resp = _make_resp(200)
    resp.text = AsyncMock(side_effect=side_effect)
    session = MagicMock()
    session.get = AsyncMock(return_value=resp)

    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, private_key=sender_hex, session=session
    )
    with pytest.raises(ThreemaSendError):
        await client.send_text_message("ABCD1234", "Hello E2E!")


@pytest.mark.parametrize(
    "side_effect",
    [aiohttp.ClientError("connection reset"), TimeoutError()],
    ids=["client_error", "timeout"],
)
async def test_send_e2e_post_connection_error(side_effect: Exception) -> None:
    """Test that a connection error or timeout on POST raises ThreemaSendError."""
    sender_hex, recipient_priv = _e2e_keys()
    pub_hex = bytes(recipient_priv.public_key).hex()

    session = MagicMock()
    session.get = AsyncMock(return_value=_make_resp(200, pub_hex))
    session.post = AsyncMock(side_effect=side_effect)

    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, private_key=sender_hex, session=session
    )
    with pytest.raises(ThreemaSendError):
        await client.send_text_message("ABCD1234", "Hello E2E!")


# ── session lifecycle ─────────────────────────────────────────────────────


async def test_no_session_raises_without_context_manager() -> None:
    """Test using the client without a session or context manager raises."""
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET)
    with pytest.raises(RuntimeError):
        await client.validate_credentials()


async def test_context_manager_creates_and_closes_owned_session() -> None:
    """Test the client creates and closes its own session as a context manager."""
    async with ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET) as client:
        assert client._session is not None
        assert not client._session.closed
    assert client._session.closed


async def test_context_manager_does_not_close_supplied_session() -> None:
    """Test an externally supplied session is left open after the context exits."""
    session = _make_session()
    async with ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session):
        pass
    session.close.assert_not_called()


# ── retries ───────────────────────────────────────────────────────────────


def _connector_error() -> aiohttp.ClientConnectorError:
    """Create the error aiohttp raises when no connection could be established."""
    return aiohttp.ClientConnectorError(MagicMock(), OSError("connection refused"))


@pytest.mark.parametrize(
    "first",
    [
        _make_resp(500),
        _make_resp(503),
        _make_resp(429),
        aiohttp.ClientError("connection reset"),
        TimeoutError(),
    ],
    ids=["http_500", "http_503", "http_429", "client_error", "timeout"],
)
async def test_get_retried_on_transient_failure(
    first: MagicMock | Exception, mock_sleep: AsyncMock
) -> None:
    """Test a GET is retried after a transient failure."""
    session = MagicMock()
    session.get = AsyncMock(side_effect=[first, _make_resp(200, "100")])
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    await client.validate_credentials()
    assert session.get.await_count == 2
    mock_sleep.assert_awaited_once()


async def test_get_retried_on_read_error() -> None:
    """Test a GET is retried if reading the response body fails."""
    broken = _make_resp(200)
    broken.text = AsyncMock(side_effect=aiohttp.ClientPayloadError("dropped"))
    session = MagicMock()
    session.get = AsyncMock(side_effect=[broken, _make_resp(200, "100")])
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    await client.validate_credentials()
    assert session.get.await_count == 2


async def test_get_gives_up_after_max_retries(mock_sleep: AsyncMock) -> None:
    """Test retries stop after max_retries, with growing backoff delays."""
    session = _make_session(get_resp=_make_resp(500))
    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session, max_retries=2
    )
    with pytest.raises(ThreemaConnectionError):
        await client.validate_credentials()
    assert session.get.await_count == 3
    first, second = (call.args[0] for call in mock_sleep.await_args_list)
    assert 0.5 <= first <= 1.0
    assert 1.0 <= second <= 2.0


async def test_retries_disabled() -> None:
    """Test max_retries=0 sends each request exactly once."""
    session = _make_session(get_resp=_make_resp(500))
    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session, max_retries=0
    )
    with pytest.raises(ThreemaConnectionError):
        await client.validate_credentials()
    session.get.assert_awaited_once()


def test_negative_max_retries_rejected() -> None:
    """Test a negative max_retries is rejected."""
    with pytest.raises(ValueError):
        ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, max_retries=-1)


async def test_auth_error_not_retried() -> None:
    """Test a 401 is never retried."""
    session = _make_session(get_resp=_make_resp(401))
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaAuthError):
        await client.validate_credentials()
    session.get.assert_awaited_once()


@pytest.mark.parametrize(
    "outcome",
    [_make_resp(500), aiohttp.ServerDisconnectedError(), TimeoutError()],
    ids=["http_500", "disconnected", "timeout"],
)
async def test_send_not_retried_when_possibly_delivered(
    outcome: MagicMock | Exception,
) -> None:
    """Test a send is not retried if the Gateway may have accepted the message."""
    session = MagicMock()
    session.post = AsyncMock(side_effect=[outcome, _make_resp(200, "msg123")])
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaSendError):
        await client.send_text_message("ABCD1234", "Hello!")
    session.post.assert_awaited_once()


async def test_send_not_retried_on_read_error() -> None:
    """Test a send is not retried if only reading the response failed."""
    resp = _make_resp(200)
    resp.text = AsyncMock(side_effect=aiohttp.ClientPayloadError("dropped"))
    session = _make_session(post_resp=resp)
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaSendError):
        await client.send_text_message("ABCD1234", "Hello!")
    session.post.assert_awaited_once()


@pytest.mark.parametrize(
    "first",
    [_make_resp(429), _connector_error()],
    ids=["http_429", "connect_error"],
)
async def test_send_retried_when_not_delivered(first: MagicMock | Exception) -> None:
    """Test a send is retried if the Gateway definitely did not accept it."""
    session = MagicMock()
    session.post = AsyncMock(side_effect=[first, _make_resp(200, "msg123")])
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    assert await client.send_text_message("ABCD1234", "Hello!") == "msg123"
    assert session.post.await_count == 2


async def test_send_e2e_retry_reuses_encrypted_payload() -> None:
    """Test a retried E2E send posts the identical nonce and box again."""
    sender_hex, recipient_priv = _e2e_keys()
    session = MagicMock()
    session.get = AsyncMock(
        return_value=_make_resp(200, bytes(recipient_priv.public_key).hex())
    )
    session.post = AsyncMock(side_effect=[_make_resp(429), _make_resp(200, "msg456")])
    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, private_key=sender_hex, session=session
    )
    assert await client.send_text_message("ABCD1234", "Hello E2E!") == "msg456"
    session.get.assert_awaited_once()
    first, second = session.post.await_args_list
    assert first == second


# ── rate limiting (HTTP 429) ──────────────────────────────────────────────


async def test_rate_limit_honors_retry_after(mock_sleep: AsyncMock) -> None:
    """Test the Retry-After header determines the delay before the retry."""
    session = MagicMock()
    session.post = AsyncMock(
        side_effect=[
            _make_resp(429, headers={"Retry-After": "7"}),
            _make_resp(200, "msg123"),
        ]
    )
    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session, rate_limit=None
    )
    assert await client.send_text_message("ABCD1234", "Hello!") == "msg123"
    mock_sleep.assert_awaited_once_with(7.0)


async def test_rate_limit_exhausted_raises() -> None:
    """Test a persistent 429 raises ThreemaRateLimitError with retry_after."""
    session = _make_session(post_resp=_make_resp(429, headers={"Retry-After": "2"}))
    client = ThreemaGatewayClient(
        MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session, rate_limit=None
    )
    with pytest.raises(ThreemaRateLimitError) as exc_info:
        await client.send_text_message("ABCD1234", "Hello!")
    assert exc_info.value.retry_after == 2.0
    assert isinstance(exc_info.value, ThreemaSendError)
    assert isinstance(exc_info.value, ThreemaConnectionError)
    assert session.post.await_count == 4


async def test_rate_limit_long_retry_after_raises_immediately(
    mock_sleep: AsyncMock,
) -> None:
    """Test a Retry-After beyond the maximum delay is not waited for."""
    session = _make_session(post_resp=_make_resp(429, headers={"Retry-After": "3600"}))
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    with pytest.raises(ThreemaRateLimitError) as exc_info:
        await client.send_text_message("ABCD1234", "Hello!")
    assert exc_info.value.retry_after == 3600.0
    session.post.assert_awaited_once()
    mock_sleep.assert_not_awaited()


async def test_rate_limit_pauses_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test a 429 holds back other requests of the same client."""
    session = MagicMock()
    session.post = AsyncMock(
        side_effect=[
            _make_resp(429, headers={"Retry-After": "7"}),
            _make_resp(200, "msg123"),
        ]
    )
    client = ThreemaGatewayClient(MOCK_GATEWAY_ID, MOCK_API_SECRET, session=session)
    pause = MagicMock()
    monkeypatch.setattr(client._rate_limiter, "pause", pause)
    await client.send_text_message("ABCD1234", "Hello!")
    pause.assert_called_once_with(7.0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("5", 5.0),
        ("-3", 0.0),
        ("soon", None),
        ("nan", None),
    ],
)
def test_parse_retry_after(value: str | None, expected: float | None) -> None:
    """Test parsing of Retry-After delays."""
    assert _parse_retry_after(value) == expected


def test_parse_retry_after_http_date() -> None:
    """Test parsing of a Retry-After HTTP date."""
    when = datetime.now(UTC) + timedelta(seconds=20)
    parsed = _parse_retry_after(format_datetime(when, usegmt=True))
    assert parsed is not None
    assert 18 <= parsed <= 20
