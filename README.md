# aiothreema

Async Python client for the [Threema Gateway](https://gateway.threema.ch/) HTTP API — send simple or end-to-end encrypted text messages from `asyncio` code.

This library implements the Gateway's HTTP wire protocol and NaCl-based end-to-end encryption directly (the official `threema.gateway` SDK is unmaintained), built on `aiohttp` and `PyNaCl`.

## Install

```bash
pip install aiothreema
```

## Usage

```python
import asyncio

from aiothreema import ThreemaGatewayClient


async def main() -> None:
    async with ThreemaGatewayClient("*GATEWAY", "api-secret") as client:
        await client.validate_credentials()
        message_id = await client.send_text_message("ABCD1234", "Hello!")
        print(message_id)


asyncio.run(main())
```

### End-to-end encryption

Pass a private key to send E2E-encrypted messages. The recipient's public key is looked up automatically via the Gateway's `/pubkeys/{id}` endpoint.

```python
async with ThreemaGatewayClient(
    "*GATEWAY", "api-secret", private_key="<64-char hex>"
) as client:
    await client.send_text_message("ABCD1234", "Hello, encrypted!")
```

### Generating a key pair

```python
from aiothreema import generate_key_pair, derive_public_key

private_key, public_key = generate_key_pair()
# Register public_key with your Gateway account at gateway.threema.ch,
# then store private_key securely — it cannot be recovered.

assert derive_public_key(private_key) == public_key
```

### Checking remaining credits

```python
remaining = await client.get_credits()  # int
```

### Using an existing `aiohttp.ClientSession`

When embedding this client in a larger application (e.g. a long-lived service that already manages its own session pool), pass a session explicitly instead of using the context-manager form — the client will not close a session it doesn't own:

```python
client = ThreemaGatewayClient("*GATEWAY", "api-secret", session=my_session)
await client.send_text_message("ABCD1234", "Hello!")
```

## Rate limiting and retries

Each client throttles its own requests and retries transient failures:

```python
client = ThreemaGatewayClient(
    "*GATEWAY",
    "api-secret",
    rate_limit=10,  # max requests per second, None to disable (default: 10)
    max_retries=3,  # retries per request, 0 to disable (default: 3)
)
```

- Retries use exponential backoff with jitter (about 1s, 2s, 4s, … capped at 30s).
- On HTTP 429 the Gateway's `Retry-After` header is honored, and all other requests of the client are held back for that long. If the requested wait exceeds 30s, or the retries are used up, `ThreemaRateLimitError` is raised with the wait in `retry_after`.
- Lookups (credits, public keys) are also retried on HTTP 5xx, connection errors and timeouts.
- Sending a message is only retried when the Gateway definitely did not accept it (HTTP 429, or the connection could not be established). After a timeout or HTTP 5xx the message may already be on its way, so the error is raised instead of risking a duplicate.

Note that an end-to-end encrypted send counts as two requests (public key lookup and send).

## Errors

All errors inherit from `ThreemaGatewayError`:

- `ThreemaAuthError` — the Gateway ID or API secret was rejected.
- `ThreemaConnectionError` — a network/transport failure talking to the Gateway.
- `ThreemaSendError` — sending a message, or resolving a recipient's public key, failed.
- `ThreemaNoCreditsError` — the account is out of credits (HTTP 402 on send). Subclasses `ThreemaSendError`.
- `ThreemaRateLimitError` — the Gateway kept answering HTTP 429. Subclasses both `ThreemaSendError` and `ThreemaConnectionError`, so existing handlers keep catching it.

## Development

```bash
pip install -e ".[test]"
pytest --cov=aiothreema
```

## License

MIT
