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

### Gateway QR code

Recipients can verify the Gateway's public key by scanning its Threema ID QR code (`3mid:<id>,<public key>`) in the Threema app:

```python
from aiothreema import generate_qr_code

svg = generate_qr_code(client.gateway_id, client.public_key)
png = generate_qr_code(client.gateway_id, client.public_key, kind="png", scale=8)
```

`client.public_key` is derived from the private key, and is `None` for simple (non-E2E) mode. Rendering is CPU-bound, so run it in an executor when calling it from an event loop. `qr_code_payload()` returns just the encoded text.

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

### Roadmap

#### Released
- **0.1.0** — Gateway client extracted from Home Assistant: basic and end-to-end
  encrypted text messages, key pair generation, public key derivation
- **0.2.0** — Dedicated errors for no credits (`ThreemaNoCreditsError`) and rate
  limiting (`ThreemaRateLimitError`), remaining credits (`get_credits()`),
  improved logging
- **0.3.0** — `public_key` property on the client; Threema ID QR codes
  (`generate_qr_code()`, `qr_code_payload()`) for verifying a gateway's public key

#### Next
- **Strict key validation** — reject private/public keys that aren't exactly
  64 hex characters with a clear error; `bytes.fromhex()` tolerates whitespace,
  so padded keys currently fail later with an unhelpful message
- **Test suite: assert real request payloads** — check endpoint URLs and form
  fields (`from`, `secret`, `to`, `text`) instead of only `assert_awaited_once()`;
  for end-to-end messages, decrypt `nonce`/`box` with the recipient's key and
  assert the plaintext

#### Planned
- **Incoming messages** — verify and decrypt Gateway callback (webhook)
  requests, including MAC check, and expose typed message objects
- **Images and files** — blob upload and end-to-end encrypted file messages
- **Receive Messages** — Duplex communication. Not only send, but also receive messages which trigger something. (did one just say HoomeAssistant-augmented Threema Bot?)
- **Delivery receipts** — parse delivery/read receipts from callbacks *(suggested)*


### Ideas
- **Lookups** — Threema ID by phone number/email hash, public key lookup and
  recipient capabilities (Gateway API endpoints) *(suggested)*


## License

MIT
