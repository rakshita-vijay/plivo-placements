#!/usr/bin/env python3
"""Command-line client for the IVR demo.

Talks to the running FastAPI service over HTTP — it never touches Plivo
directly — so it works against a local server or a deployed one.

Usage:
    python cli/trigger_call.py                        # dial DEFAULT_DESTINATION_NUMBER
    python cli/trigger_call.py --to +919876543210      # dial a specific number
    python cli/trigger_call.py --to +91... --watch      # dial and stream status
    python cli/trigger_call.py --status <session_id>    # check a past call
    python cli/trigger_call.py --hangup <session_id>    # end a live call
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

import httpx

DEFAULT_SERVER_URL = os.environ.get("IVR_SERVER_URL", "http://localhost:8000")
POLL_INTERVAL_SECONDS = 2.0
WATCH_TIMEOUT_SECONDS = 300
TERMINAL_STAGES = {"completed", "failed"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trigger and monitor calls against the InspireWorks IVR demo.",
    )
    parser.add_argument(
        "--server",
        default=DEFAULT_SERVER_URL,
        help=f"Base URL of the running service (default: {DEFAULT_SERVER_URL})",
    )
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--to", metavar="NUMBER", help="Destination number to call")
    action_group.add_argument("--status", metavar="SESSION_ID", help="Print a session's status")
    action_group.add_argument("--hangup", metavar="SESSION_ID", help="End a live call")
    action_group.add_argument(
        "--list", action="store_true", help="List recent call sessions"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="After placing a call, poll and print status until it ends",
    )
    return parser.parse_args(argv)


def place_call(client: httpx.Client, to_number: str | None) -> dict[str, Any]:
    payload = {"to_number": to_number} if to_number else {}
    response = client.post("/api/calls", json=payload)
    response.raise_for_status()
    return response.json()


def get_status(client: httpx.Client, session_id: str) -> dict[str, Any]:
    response = client.get(f"/api/calls/{session_id}")
    response.raise_for_status()
    return response.json()


def hangup(client: httpx.Client, session_id: str) -> None:
    response = client.delete(f"/api/calls/{session_id}")
    response.raise_for_status()


def list_recent(client: httpx.Client) -> list[dict[str, Any]]:
    response = client.get("/api/calls")
    response.raise_for_status()
    return response.json()


def print_session_summary(session: dict[str, Any]) -> None:
    print(f"  session_id : {session['session_id']}")
    print(f"  call_uuid  : {session.get('call_uuid') or '(not answered yet)'}")
    print(f"  stage      : {session['stage']}")
    print(f"  language   : {session.get('language') or '(not chosen yet)'}")
    print(f"  authed     : {session['is_authenticated']}")
    print(f"  otp tries  : {session['otp_attempts']}")


def watch_session(client: httpx.Client, session_id: str) -> None:
    print("\nWatching call progress (Ctrl+C to stop watching without ending the call)...\n")
    deadline = time.monotonic() + WATCH_TIMEOUT_SECONDS
    last_event_count = 0

    try:
        while time.monotonic() < deadline:
            session = get_status(client, session_id)
            events = session["events"]
            for event in events[last_event_count:]:
                print(f"  [{event['at']}] {event['type']} {_event_detail(event)}")
            last_event_count = len(events)

            if session["stage"] in TERMINAL_STAGES:
                print(f"\nCall finished in stage: {session['stage']}")
                return
            time.sleep(POLL_INTERVAL_SECONDS)
        print("\nStopped watching after timeout; the call may still be in progress.")
    except KeyboardInterrupt:
        print("\nStopped watching (call left running).")


def _event_detail(event: dict[str, Any]) -> str:
    extra = {k: v for k, v in event.items() if k not in {"at", "type"}}
    return " ".join(f"{key}={value}" for key, value in extra.items())


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    with httpx.Client(base_url=args.server, timeout=15.0) as client:
        try:
            if args.status:
                print(f"Status for session {args.status}:")
                print_session_summary(get_status(client, args.status))
                return 0

            if args.hangup:
                hangup(client, args.hangup)
                print(f"Ended call for session {args.hangup}")
                return 0

            if args.list:
                sessions = list_recent(client)
                if not sessions:
                    print("No recent calls.")
                    return 0
                print(f"{'session_id':<34} {'stage':<20} {'language':<8} {'destination'}")
                for session in sessions:
                    print(
                        f"{session['session_id']:<34} {session['stage']:<20} "
                        f"{session.get('language') or '-':<8} {session['destination_number']}"
                    )
                return 0

            # Default action: place a call.
            print(f"Placing outbound call via {args.server} ...")
            result = place_call(client, args.to)
            print("Call queued:")
            print(f"  session_id      : {result['session_id']}")
            print(f"  request_uuid    : {result['request_uuid']}")
            print(f"  destination     : {result['destination_number']}")
            print(f"  caller (Plivo)  : {result['caller_number']}")
            print(
                "\nAnswer the phone now — the bot will ask for your 4-digit access code."
            )

            if args.watch:
                watch_session(client, result["session_id"])
            else:
                print(
                    f"\nCheck progress any time with:\n"
                    f"  python cli/trigger_call.py --status {result['session_id']}"
                )
            return 0

        except httpx.ConnectError:
            print(
                f"Could not reach {args.server}. Is the server running?\n"
                f"  uvicorn app.main:app --reload --port 8000",
                file=sys.stderr,
            )
            return 1
        except httpx.HTTPStatusError as error:
            detail = _safe_error_detail(error.response)
            print(f"Request failed ({error.response.status_code}): {detail}", file=sys.stderr)
            return 1


def _safe_error_detail(response: httpx.Response) -> str:
    try:
        return response.json().get("detail", response.text)
    except ValueError:
        return response.text


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
