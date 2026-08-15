# Getting Started — Plivo IVR Demo

A complete path from "downloaded the zip" to "my phone just rang and I talked to a bot." Follow this in order — don't skip ahead.

You'll need two terminal windows open at the same time in the later steps, and about 15–20 minutes.

---

## Before you start

Check off each of these. If any are missing, the linked note tells you how to get them.

- [ ] **A computer with Python 3.11 or newer.** Check by opening a terminal and running:
  ```bash
  python3 --version
  ```
  If this fails or shows something below 3.11, install Python from [python.org/downloads](https://www.python.org/downloads/) first.

- [ ] **A terminal app.**
  - Mac: **Terminal** (Applications → Utilities) or **iTerm**
  - Windows: **PowerShell** (search "PowerShell" in the Start menu) — commands below note where Windows differs
  - Linux: whatever terminal you normally use

- [ ] **A phone that can receive calls** (the one you'll dial).

- [ ] **The zip file** I gave you (`plivo-ivr-demo.zip`).

That's it — everything else (ngrok, Python packages) gets installed in the steps below.

---

## Part 1 — Get the code onto your machine

1. Find `plivo-ivr-demo.zip` in your Downloads folder.
2. Double-click it to extract (Mac/Windows do this natively; on Linux, right-click → Extract, or `unzip plivo-ivr-demo.zip`).
3. You should now have a folder called `plivo-ivr-demo` with folders like `app`, `cli`, `tests` inside it.
4. Open your terminal and move into that folder:
   ```bash
   cd ~/Downloads/plivo-ivr-demo
   ```
   (Adjust the path if you extracted it somewhere else. Tip: type `cd `, then drag the folder from Finder/Explorer into the terminal window — it fills in the path for you.)
5. Confirm you're in the right place:
   ```bash
   ls
   ```
   You should see `app`, `cli`, `tests`, `README.md`, `requirements.txt`, etc.

---

## Part 2 — Install dependencies

This creates an isolated Python environment so the project's packages don't clash with anything else on your machine.

**Mac / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

You'll know it worked if your terminal prompt now starts with `(.venv)`. This install takes a minute or two. Leave this terminal window open — you'll use it to start the server later.

> Every time you open a **new** terminal window to work on this project, you need to re-run the `source .venv/bin/activate` (or `.venv\Scripts\Activate.ps1`) line first, or Python won't find the installed packages.

---

## Part 3 — Install ngrok

Plivo needs to reach your laptop over the internet, and your laptop doesn't normally have a public address. ngrok solves this by giving you a temporary public URL that tunnels straight to `localhost:8000` on your machine.

1. Go to **[ngrok.com](https://ngrok.com/)** and sign up for a free account.
2. Install it:
   - **Mac (with Homebrew):** `brew install ngrok`
   - **Windows/Mac/Linux (no Homebrew):** download the binary from [ngrok.com/download](https://ngrok.com/download), unzip it, and note where you put it
3. After signing up, ngrok's dashboard shows you an **authtoken** — a long string under "Your Authtoken." Copy it, then run:
   ```bash
   ngrok config add-authtoken YOUR_TOKEN_HERE
   ```
   You only need to do this once, ever, on this machine.
4. Confirm it works:
   ```bash
   ngrok version
   ```

Don't start the tunnel yet — that comes in Part 5.

---

## Part 4 — Configure the app

Copy the template and open it in any text editor (TextEdit, Notepad, VS Code — whatever you have):

```bash
cp .env.example .env
```

Replace the entire contents of `.env` with this — it's already filled in with the Plivo credentials from your assignment doc. **You only need to change the one line marked TODO:**

```dotenv
PLIVO_AUTH_ID=MAMTAWMGI0MZCTNTYZZS
PLIVO_AUTH_TOKEN=YTI5OGVjYjYtZTE1OS00NWRmLTk3MGUtNzJhNjc2
PLIVO_CALLER_NUMBER=+91 80 3545 4161
LIVE_ASSOCIATE_NUMBER=02264236412
DEFAULT_COUNTRY_CODE=91

DEFAULT_DESTINATION_NUMBER=+91XXXXXXXXXX
# ^ TODO: replace with YOUR phone number, in +91XXXXXXXXXX format

OTP_CODE=1234
OTP_LENGTH=4
OTP_MAX_ATTEMPTS=0
MAX_CONSECUTIVE_INVALID_INPUTS=3

PUBLIC_BASE_URL=https://placeholder.ngrok-free.app
# ^ you'll replace this in Part 6, after starting ngrok — leave it for now

VALIDATE_PLIVO_SIGNATURE=true
APP_NAME=InspireWorks IVR Demo
ENVIRONMENT=development
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO
LOG_FORMAT=console
CALL_SESSION_TTL_SECONDS=3600
```

Save the file. **Important:** it must be named exactly `.env` (not `.env.txt` — some editors add `.txt` automatically; check your file manager shows hidden/dotfiles if you can't see it after saving).

> These are real, billable credentials. Every call this places costs real account credit — that's expected for the assignment, just don't leave the server running and dialing all day.

---

## Part 5 — Start the server and the tunnel

You need **two terminal windows open at once** from here on.

### Terminal 1 — the app server

If it's not already open from Part 2, open a terminal, `cd` into the project folder, and activate the environment again:

```bash
cd ~/Downloads/plivo-ivr-demo
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
```

Then start the server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

You should see log lines ending in something like `Application startup complete.` **Leave this running** — this window is now your server. Don't close it or press Ctrl+C until you're done testing.

### Terminal 2 — the tunnel

Open a **second, separate terminal window**. You don't need to activate the virtual environment here — ngrok isn't a Python tool.

```bash
ngrok http 8000
```

ngrok will show a screen that stays open, with a line like:

```
Forwarding    https://a1b2-203-0-113-42.ngrok-free.app -> http://localhost:8000
```

**Copy that `https://...ngrok-free.app` URL.** You'll need it in the next step. Leave this window running too.

---

## Part 6 — Point the app at your tunnel

Go back to your `.env` file and replace the placeholder line:

```dotenv
PUBLIC_BASE_URL=https://a1b2-203-0-113-42.ngrok-free.app
```

(Use **your** actual ngrok URL from Terminal 2 — yours will be different. No trailing slash.)

Save the file, then go back to **Terminal 1** (the server), stop it with `Ctrl+C`, and start it again:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The server only reads `.env` on startup, so this restart is required every time you change it.

### Sanity check before dialing

Open this URL in your web browser (use your real ngrok URL):

```
https://a1b2-203-0-113-42.ngrok-free.app/health
```

You should see JSON like:
```json
{"status": "ok", "caller_number": "+918*******61", ...}
```

If you see that, everything is wired up correctly and reachable from the internet — exactly what Plivo needs.

---

## Part 7 — Trigger the call

Open a **third terminal tab** (or use the browser) — Terminals 1 and 2 both need to keep running.

### Option A — Browser control panel (easiest)

Go to **http://localhost:8000** in your browser. Type your phone number into the "Destination number" box and click **Place Call**.

### Option B — Command line

```bash
cd ~/Downloads/plivo-ivr-demo
source .venv/bin/activate
python cli/trigger_call.py --to +91XXXXXXXXXX --watch
```
(Replace with your number. `--watch` prints live updates as the call progresses.)

Either way — **your phone will ring within a few seconds.** Answer it.

---

## Part 8 — Walk through the call

1. The bot greets you and asks for a 4-digit access code.
2. **Enter a wrong code first** (e.g. `0000`) on your phone's keypad — the bot tells you it's incorrect and asks again.
3. **Enter `1234`** (the correct code, per `OTP_CODE` in `.env`) — the bot confirms you're verified.
4. **Press 1** for English or **2** for Spanish.
5. You'll hear the main menu: **press 1** to hear a short audio clip (then you're returned to this menu), or **press 2** to be transferred to the associate/placeholder number.
6. Hang up whenever you're satisfied, or let it complete naturally.

While this is happening, if you used the browser control panel, watch the event log update live on screen — it shows every step (`otp_rejected`, `otp_accepted`, `language_selected`, etc.) as it happens.

---

## Shutting everything down

When you're done:
1. Terminal 1 (server): press `Ctrl+C`
2. Terminal 2 (ngrok): press `Ctrl+C`

Both are safe to close after that.

---

## Running the automated tests (optional, no phone needed)

If you want to confirm the code itself is correct without placing a real call:

```bash
cd ~/Downloads/plivo-ivr-demo
source .venv/bin/activate
pytest
```

This runs 81 tests against a fake Plivo backend — no internet, no phone call, no cost. You should see `81 passed`.

---

## Troubleshooting

| Symptom | What's wrong | Fix |
|---|---|---|
| `command not found: python3` | Python isn't installed or isn't on PATH | Install from python.org, restart your terminal |
| Phone never rings | `.env` has a typo, or the server never restarted after editing it | Check `http://localhost:8000/health` for errors; restart Terminal 1 |
| Call connects but the bot says nothing | `PUBLIC_BASE_URL` is stale — usually because ngrok was restarted and gave a new URL | Copy the *current* ngrok URL into `.env`, restart the server |
| `403 Forbidden` in the server's terminal log | The URL Plivo called doesn't exactly match `PUBLIC_BASE_URL` | Make sure there's no typo and no trailing slash mismatch |
| ngrok says "authentication failed" | You skipped `ngrok config add-authtoken` | Go back to Part 3, step 3 |
| `ModuleNotFoundError` when starting the server | Virtual environment isn't activated in that terminal | Run `source .venv/bin/activate` again in that window |

---

## Quick reference — every command in one place

```bash
# One-time setup
cd ~/Downloads/plivo-ivr-demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit .env as shown in Part 4
ngrok config add-authtoken YOUR_TOKEN_HERE

# Every time you want to run a demo (two terminals)
# Terminal 1:
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2:
ngrok http 8000
# → copy the https URL into .env as PUBLIC_BASE_URL, restart Terminal 1

# Terminal 3 (trigger the call):
source .venv/bin/activate
python cli/trigger_call.py --to +91XXXXXXXXXX --watch

# Run the test suite instead of a real call:
pytest
```
