# Call Flow

This is the exact state machine implemented in `app/routers/ivr.py`. Every box
is a webhook endpoint; every edge is either a Plivo `<Redirect>`/`action`
callback or a caller keypress.

```mermaid
flowchart TD
    A[["POST /api/calls\n(REST trigger)"]] -->|Plivo dials the caller| B(["POST /ivr/answer"])
    B --> C["POST /ivr/otp/prompt\nSpeak + GetDigits (4 digits)"]

    C -->|silence x1| C
    C -->|silence x3 in a row| Z1(["Hangup — goodbye"])
    C -->|digits entered| D{"POST /ivr/otp/verify\nCorrect?"}

    D -->|"no — re-prompt\n(unlimited by default)"| C
    D -->|yes| E["POST /ivr/menu/language\nLevel 1: 1=English 2=Spanish"]

    E -->|silence / invalid x3| Z1
    E -->|digit entered| F{"POST /ivr/menu/language/select"}
    F -->|invalid digit| E
    F -->|1 or 2| G["POST /ivr/menu/main\nLevel 2: 1=Audio 2=Associate"]

    G -->|silence / invalid x3| Z2(["Hangup — goodbye"])
    G -->|digit entered| H{"POST /ivr/menu/main/select"}
    H -->|invalid digit| G

    H -->|"1"| I["Play hosted MP3"]
    I -->|redirect| G

    H -->|"2"| J["<Dial> associate number"]
    J --> K{"POST /ivr/associate/status\nDialStatus"}
    K -->|completed| Z3(["Hangup — goodbye"])
    K -->|busy / no-answer / failed| G

    B -.->|hangup event| L["POST /ivr/events/hangup\n(closes session audit trail)"]
    B -.->|answer_url unreachable| M["POST /ivr/events/fallback\n(fails gracefully)"]
```

## Guard rails baked into every box

- **Every `<GetDigits>` is followed by a `<Redirect>`.** If Plivo gets no DTMF
  at all, it does not call `action` — it falls through to the next XML
  element. Without that trailing redirect, silence would kill the call
  outright instead of re-prompting.
- **Authentication is re-checked on every hop**, not just at the OTP step.
  Callback URLs are guessable; `E`, `F`, `G`, `H` all bounce an
  unauthenticated caller back to the OTP prompt rather than trusting that a
  session marked authenticated earlier is still theirs.
- **Wrong OTP re-prompts indefinitely by default** (`OTP_MAX_ATTEMPTS=0`), per
  the assignment. Silence and off-menu keypresses are capped separately
  (`MAX_CONSECUTIVE_INVALID_INPUTS`, default 3) so a forgotten handset can't
  hold the line open forever — that cap is a safety net, not a spec
  requirement, and is documented as such in `.env.example`.
