# InspireWorks IVR Demo

An outbound-calling demo built on **Plivo's Voice API**: dial a number, authenticate the caller with a DTMF one-time-code, then walk them through a two-level IVR menu — language selection, then a choice of a short audio message or a live transfer.

Built for the Plivo Forward Deployed Engineer technical assignment. Every requirement in the assignment brief is implemented; see [Requirements → implementation map](#requirements--implementation-map) at the bottom.

```
Trigger (UI / CLI / API)  →  Plivo dials your phone  →  OTP  →  Language menu  →  Main menu  →  Audio | Live associate
```

New to this stack, or want every command spelled out with no assumptions? **[`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)** is a zero-to-live-call walkthrough. This README is the concise version.

A full call-flow diagram is in [`docs/CALL_FLOW.md`](docs/CALL_FLOW.md).

---

## Contents

- [InspireWorks IVR Demo](#inspireworks-ivr-demo)
  - [Contents](#contents)
  - [Architecture](#architecture)
  - [Setup instructions](#setup-instructions)
    - [Expose the server publicly](#expose-the-server-publicly)
  - [Required Plivo credentials](#required-plivo-credentials)
  - [Steps to run and test](#steps-to-run-and-test)
    - [Run the server](#run-the-server)
    - [Trigger a call](#trigger-a-call)
    - [Walking the demo call](#walking-the-demo-call)
    - [Run the automated tests](#run-the-automated-tests)
  - [Configuration reference](#configuration-reference)
  - [Project structure](#project-structure)
  - [How authentication and branching work](#how-authentication-and-branching-work)
  - [Troubleshooting](#troubleshooting)
  - [Security notes](#security-notes)
  - [Docker](#docker)
  - [Requirements → implementation map](#requirements--implementation-map)

---

## Architecture

A single FastAPI service plays two roles:

1. **Control plane** (`/api/*`) — a REST API the browser control panel and CLI use to place calls and poll their status. This never talks to a caller's phone directly.
2. **Telephony plane** (`/ivr/*`) — webhooks that **only Plivo calls**. Each one receives the caller's DTMF input and returns [Plivo XML](https://www.plivo.com/docs/voice/xml/) describing what should happen next. This is the actual IVR logic.

```
┌────────────┐     places call      ┌──────────────┐     dials your phone     ┌───────────┐
│  Browser / │ ───────────────────► │   This app    │ ───────────────────────► │  Plivo    │
│  CLI       │                      │  (FastAPI)    │                          │  Voice API│
└────────────┘                      └──────┬────────┘                         └─────┬─────┘
                                            │                                        │
                                            │        webhooks (answer, digits,       │
                                            │◄────── dial status, hangup) ───────────┘
                                            │        signed with HMAC-SHA256
                                            ▼
                                   returns Plivo XML
                                (Speak / GetDigits / Play / Dial / Redirect)
```

Because Plivo fetches call-flow XML over the public internet, **this service must be reachable from the internet**. In local development that means tunnelling with `ngrok`; in production it means a real HTTPS ingress.

State (which stage of the IVR a call is in, whether it's authenticated, how many wrong OTPs it's had) lives in an in-process, TTL-bounded store keyed by an application-owned session ID that's threaded through every callback URL — see [How authentication and branching work](#how-authentication-and-branching-work).

---

## Setup instructions

**Prerequisites:** Python 3.11+, a [Plivo](https://www.plivo.com/) account with a voice-enabled number, [ngrok](https://ngrok.com/) (or any HTTPS tunnel) for local development, and a phone to receive the demo call.

```bash
git clone <this-repo-url>          # or: unzip the delivered archive
cd plivo-ivr-demo

# Create a virtual environment and install dependencies
make install          # or: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
source .venv/bin/activate

cp .env.example .env
```

Edit `.env` — see [Required Plivo credentials](#required-plivo-credentials) below for what goes in it.

### Expose the server publicly

Plivo cannot reach `localhost`, so the server needs a public URL:

```bash
# Terminal 1:
make run                     # starts uvicorn on :8000

# Terminal 2:
ngrok http 8000
```

`ngrok` prints an HTTPS forwarding URL like `https://a1b2c3d4.ngrok-free.app`. Put it in `.env`:

```dotenv
PUBLIC_BASE_URL=https://a1b2c3d4.ngrok-free.app
```

Restart the server (`Ctrl+C`, then `make run` again) so it picks up the new value — the app reads `.env` once at startup.

> **ngrok's free-tier URL changes every restart.** Update `PUBLIC_BASE_URL` and restart the server each time you get a new tunnel URL, or use a paid ngrok static domain to avoid this.

For a fully spelled-out version of every step above (including installing ngrok and troubleshooting each one), see [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md).

---

## Required Plivo credentials

From the [Plivo Console](https://console.plivo.com/dashboard/) → **Account → Auth ID & Auth Token**:

| Variable | What it is | Where to find it |
|---|---|---|
| `PLIVO_AUTH_ID` | Your account's Auth ID | Console → Account |
| `PLIVO_AUTH_TOKEN` | Your account's Auth Token (secret) | Console → Account |
| `PLIVO_CALLER_NUMBER` | A voice-enabled Plivo number on your account | Console → Phone Numbers |

These three go in `.env`, which is git-ignored — never commit real credentials (see [Security notes](#security-notes)). The assignment brief supplied a specific Auth ID, Auth Token, and caller number for this exercise; treat those as **already used** — rotate the token before this repository is made public, since anyone with it can place calls billed to that account.

A complete `.env` looks like this:

```dotenv
PLIVO_AUTH_ID=MAxxxxxxxxxxxxxxxxxxx
PLIVO_AUTH_TOKEN=your_plivo_auth_token
PLIVO_CALLER_NUMBER=+918035454161
LIVE_ASSOCIATE_NUMBER=02264236412
DEFAULT_DESTINATION_NUMBER=+91XXXXXXXXXX     # your phone, for one-click testing
OTP_CODE=1234                                 # placeholder per spec; swap for your birthdate DDMM if you prefer
PUBLIC_BASE_URL=                              # fill in after starting ngrok, above
```

---

## Steps to run and test

### Run the server

```bash
make run
# or directly:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** for the control panel, or check **http://localhost:8000/health** to confirm the service sees your configuration correctly (masked caller/associate numbers, whether signature verification is on). Interactive API docs are auto-generated at **http://localhost:8000/docs**.

### Trigger a call

Three equivalent ways:

**1. Browser control panel** (`http://localhost:8000`) — type a destination number, click **Place Call**. Watch the stepper and event log update live as the call moves through OTP → language menu → main menu.

**2. CLI**

```bash
python cli/trigger_call.py --to +91XXXXXXXXXX --watch
python cli/trigger_call.py --list                    # recent calls
python cli/trigger_call.py --status <session_id>      # one call's detail
python cli/trigger_call.py --hangup <session_id>       # end a live call
```

**3. Raw API**

```bash
curl -X POST http://localhost:8000/api/calls \
  -H "Content-Type: application/json" \
  -d '{"to_number": "+91XXXXXXXXXX"}'
```

Then **answer your phone** — the bot greets you and asks for the 4-digit access code.

### Walking the demo call

1. Bot asks for a 4-digit code. Enter the wrong one — it re-prompts. Enter `1234` (the shipped placeholder — matching `OTP_CODE` in `.env`, override it with your own birthdate DDMM if you'd rather) — it confirms and continues.
2. **Level 1:** press `1` for English or `2` for Spanish.
3. **Level 2:** press `1` to hear a short audio message (then you're returned to this menu), or `2` to be transferred to the associate/placeholder number.

### Run the automated tests

```bash
make test
# or: pytest
```

81 tests, no network calls — the Plivo REST client is swapped for a fake in `tests/conftest.py`, so the suite runs in well under a second and never spends call credit. Coverage:

| File | What it checks |
|---|---|
| `test_otp_authentication.py` | Constant-time OTP compare, unlimited re-prompt on wrong code, silence handling, authentication is recorded on the session |
| `test_ivr_menu_flow.py` | Level 1 / Level 2 branching, invalid-digit handling, associate dial outcomes (completed / busy / no-answer), two full call journeys end-to-end |
| `test_phone_numbers.py` | E.164 normalisation against the exact numbers from the assignment brief |
| `test_signature_verification.py` | Plivo's HMAC-SHA256 webhook signature — accepted when valid, rejected when tampered, missing, or wrong-keyed; a live FastAPI request-response round trip for both cases |
| `test_outbound_call_api.py` | The REST control plane: placing calls, status, hangup, error propagation |

Manual end-to-end verification (answer → wrong OTP → correct OTP → language menu → main menu → audio) was also run against a live `uvicorn` server over real HTTP during development, not just through the test client.

---

## Configuration reference

Every variable is documented inline in [`.env.example`](.env.example). The ones worth calling out:

| Variable | Default | Notes |
|---|---|---|
| `OTP_MAX_ATTEMPTS` | `0` | `0` = re-prompt forever on a wrong code, matching the assignment spec exactly. Set a positive number to add a hard cap. |
| `MAX_CONSECUTIVE_INVALID_INPUTS` | `3` | Not in the spec — a safety net so a silent or off-menu caller doesn't hold the line open indefinitely. Governs silence/invalid-digit timeouts only, never OTP attempts. |
| `VALIDATE_PLIVO_SIGNATURE` | `true` | Keep this on. Only disable to replay a captured webhook by hand with `curl`. |
| `DEFAULT_COUNTRY_CODE` | `91` | Applied when a number is given without a country code (e.g. the associate number `02264236412` from the brief). |
| `AUDIO_MESSAGE_URL_ENGLISH` / `_SPANISH` | Plivo's sample MP3 | Point at your own hosted MP3 if you want a custom message. |

---

## Project structure

```
app/
├── main.py                  # FastAPI app factory, lifespan, exception handling
├── dependencies.py          # Dependency-injection wiring (settings, stores, services)
├── schemas.py                # Pydantic request/response models for the REST API
├── core/
│   ├── config.py             # All environment variables, validated at startup
│   ├── models.py             # CallSession, Language, CallStage, PromptReason
│   ├── phone_numbers.py      # E.164 normalisation + log-safe masking
│   ├── security.py           # Plivo webhook HMAC-SHA256 signature verification
│   └── logging_config.py     # Console / JSON structured logging
├── ivr/
│   ├── routes.py              # Canonical webhook path constants
│   ├── callback_urls.py       # Deterministic callback URL construction
│   ├── prompts.py             # Every spoken line, English + Spanish
│   └── xml_builder.py         # Builds every Plivo XML document the app returns
├── services/
│   ├── otp_verifier.py         # Constant-time OTP comparison
│   ├── plivo_call_service.py   # Places/ends calls via Plivo's REST API
│   └── call_session_store.py   # Thread-safe, TTL-bounded session storage
├── routers/
│   ├── ivr.py                 # The 10 webhook endpoints — the actual IVR logic
│   ├── calls.py               # REST control plane: place/status/list/hangup
│   ├── health.py              # /health, /health/ready
│   └── webhook_context.py     # Parses + verifies inbound Plivo webhooks
└── static/
    └── index.html             # Browser control panel (vanilla HTML/CSS/JS)

cli/
└── trigger_call.py           # Command-line client for the REST control plane

tests/                        # 81 tests, see "Steps to run and test" above
docs/
├── GETTING_STARTED.md        # Fully-detailed, no-assumptions setup walkthrough
├── CALL_FLOW.md               # Mermaid state-machine diagram
└── DEMO_SCRIPT.md             # Shot list for the required demo video
```

---

## How authentication and branching work

A few decisions worth understanding if you're reading the code:

- **Sessions are keyed by an app-owned ID, not Plivo's.** Plivo's REST API returns a `request_uuid` when a call is *queued*; the webhooks that follow carry a different value, `CallUUID`, minted once the call leg actually exists. Rather than reconciling the two, every call gets a `session_id` at creation time, which is threaded through every callback URL (`?session_id=...`). Plivo preserves query strings across redirects, so the session survives every hop. A secondary index on `CallUUID` lets the hangup event find its session too.

- **Every `<GetDigits>` is followed by a `<Redirect>`.** If a caller enters nothing, Plivo does *not* call the `action` URL — it falls through to the next XML element. Skip the trailing redirect and a silent caller's call simply dies. This is tested explicitly (`test_silence_falls_through_to_a_redirect_not_a_dead_call`).

- **Authentication is re-checked on every menu hop**, not just once at the OTP step. Callback URLs are guessable; every `/ivr/menu/*` endpoint independently verifies `session.is_authenticated` before acting, and bounces an unauthenticated request back to the OTP prompt.

- **Wrong OTP re-prompts indefinitely by default**, exactly per the spec (`OTP_MAX_ATTEMPTS=0`). Silence and off-menu keypresses are capped separately so a forgotten handset can't hold a line open forever — see the config table above.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Phone never rings | `PLIVO_CALLER_NUMBER` isn't a number on your account, or the destination number failed E.164 normalisation — check `/health` and the API response for the actual error. |
| Call connects but the bot never speaks | `PUBLIC_BASE_URL` is stale (old ngrok URL) or points somewhere unreachable — Plivo can't fetch the answer XML. Check `/health` and hit `PUBLIC_BASE_URL/health` yourself from outside your network. |
| `403 Forbidden` on webhooks in server logs | Signature verification failed — usually because `PUBLIC_BASE_URL` doesn't exactly match the URL Plivo actually called (scheme/host mismatch), since the signature covers the full URL. |
| Silence, then the call hangs up | Working as intended — `MAX_CONSECUTIVE_INVALID_INPUTS` (default 3) has been reached with no digits entered. |
| Audio doesn't play | `AUDIO_MESSAGE_URL_ENGLISH`/`_SPANISH` must be a **publicly reachable** MP3, not something behind auth or on localhost. |
| `pytest: command not found` | Dev dependencies aren't installed — run `pip install -r requirements-dev.txt`. |

More detail, including setup-stage issues (missing Python, ngrok auth), is in [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md#troubleshooting).

---

## Security notes

- `.env` is git-ignored. Never commit real credentials — `.env.example` contains placeholders only.
- Webhook signature verification (`VALIDATE_PLIVO_SIGNATURE=true`) is on by default and rejects any `/ivr/*` request not provably signed by Plivo's HMAC-SHA256 scheme. This matters because those endpoints are, by necessity, reachable from the public internet.
- The OTP comparison uses `hmac.compare_digest` (constant-time) and the code is never written to Plivo's own request logs (`log="false"` on the `<GetDigits>`) or to this app's logs.
- Phone numbers are masked in logs (`+918*******61`) via `mask_phone_number`.
- **The Auth ID / Auth Token supplied in the original assignment brief are live credentials shared in plaintext.** Rotate them in the Plivo Console before this repository is shared publicly or pushed to GitHub.

---

## Docker

```bash
make docker-build
make docker-run        # reads .env, forwards :8000
```

Runs as a non-root user with a healthcheck against `/health`. Session state is in-process (see `call_session_store.py`), so this image is designed for a single instance; scale by implementing the `CallSessionStore` protocol against Redis before running multiple replicas.

---

## Requirements → implementation map

| Assignment requirement | Where |
|---|---|
| Outbound call from Plivo number to a target number | `POST /api/calls` → `PlivoCallService.place_call` |
| Target number via UI or config | Browser control panel dialer, CLI `--to`, or `DEFAULT_DESTINATION_NUMBER` |
| OTP prompt on answer, 4-digit DTMF | `POST /ivr/answer` → `build_otp_prompt` |
| OTP hardcoded, no database | `OTP_CODE` defaults to `1234` in `app/core/config.py` — override with a birthdate in `.env` if desired |
| Re-prompt until correct | `OTP_MAX_ATTEMPTS=0` default in `verify_otp` |
| Level 1: language (English/Spanish) | `POST /ivr/menu/language*` |
| Level 2: audio or associate transfer | `POST /ivr/menu/main*` |
| Plivo XML for call flow | `app/ivr/xml_builder.py`, `plivoxml` throughout |
| DTMF handling across all levels, branching, invalid-input handling | `app/routers/ivr.py` |
| Optional frontend | `app/static/index.html` control panel + `cli/trigger_call.py` |
| Working application | `uvicorn app.main:app`, verified live end-to-end |
| Code repository with README (setup, credentials, run/test steps) | this file |
| Demo video | shot list in `docs/DEMO_SCRIPT.md` |
| Receiver's phone number | state it in your submission email, per the assignment |
