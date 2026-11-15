"""Optional real-calendar connection probes and sync helpers; no local demo tools."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from email.utils import parseaddr
from pathlib import Path

APPLE_CALENDAR_NAME = "SOC_AI_TRANSFORM"
APPLE_CALENDAR_PROBE_TIMEOUT = 15
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
GOOGLE_CALENDAR_TIMEOUT = 30


def _applescript_date(var: str, iso: str) -> str:
    """Build an AppleScript date from ISO parts — immune to system locale
    (never feed AppleScript a formatted date string; parsing is locale-bound)."""
    d = datetime.fromisoformat(iso)
    # set day to 1 BEFORE month/year: prevents the classic AppleScript overflow
    # (if today is the 31st, setting month to a 30-day month rolls into next month)
    return (
        f"set {var} to current date\nset day of {var} to 1\n"
        f"set year of {var} to {d.year}\nset month of {var} to {d.month}\n"
        f"set day of {var} to {d.day}\nset hours of {var} to {d.hour}\n"
        f"set minutes of {var} to {d.minute}\nset seconds of {var} to 0\n"
    )


def probe_apple_calendar() -> None:
    """Verify Calendar.app automation access and find one writable calendar.

    This is deliberately read-only: Connections can test the integration
    without leaving a synthetic event or calendar behind.
    """
    if sys.platform != "darwin":
        raise RuntimeError("Apple Calendar probe is macOS-only.")
    script = '''
launch application "Calendar"
tell application "Calendar"
  repeat with cal in calendars
    try
      if writable of cal then return name of cal
    end try
  end repeat
end tell
return ""'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=APPLE_CALENDAR_PROBE_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Apple Calendar probe timed out after {APPLE_CALENDAR_PROBE_TIMEOUT}s; "
            "Calendar.app may be slow or waiting for Automation permission."
        ) from None
    except OSError as exc:
        raise RuntimeError(f"Apple Calendar probe could not run osascript ({exc}).") from None
    if result.returncode != 0:
        detail = (result.stderr or "failed").strip()[:200]
        raise RuntimeError(f"Apple Calendar probe failed: {detail}")
    if not (result.stdout or "").strip():
        raise RuntimeError("Apple Calendar has no writable calendars.")


def _record_apple_calendar_health(ok: bool, message: str) -> None:
    """Publish real runtime outcomes without making calendar sync depend on UI."""
    try:
        from SOC_AI_TRANSFORM.integrations import IntegrationState, IntegrationStatus, record_health

        state = IntegrationState.CONNECTED if ok else IntegrationState.ERROR
        record_health("apple_calendar", IntegrationStatus(state, message))
    except Exception:
        # A health-cache write must never change whether the user's event lands.
        pass


def sync_to_apple_calendar(title: str, start: str, end: str, notes: str = "") -> str:
    """Create the event in Calendar.app under the 'SOC_AI_TRANSFORM' calendar (created on
    first use). Returns a short human-readable outcome for the tool output."""
    if sys.platform != "darwin":
        return "Apple Calendar sync skipped (not macOS)."
    safe_title = title.replace("\\", "").replace('"', "'")
    safe_notes = notes.replace("\\", "").replace('"', "'")
    # Prefer a dedicated "SOC_AI_TRANSFORM" calendar, but macOS can't create calendars in
    # iCloud-only accounts via AppleScript — fall back to the first writable
    # calendar and report which one was actually used.
    script = (
        _applescript_date("startDate", start)
        + _applescript_date("endDate", end)
        + f'''
tell application "Calendar"
  if not (exists calendar "{APPLE_CALENDAR_NAME}") then
    try
      make new calendar with properties {{name:"{APPLE_CALENDAR_NAME}"}}
      delay 1
    end try
  end if
  if exists calendar "{APPLE_CALENDAR_NAME}" then
    set targetCal to calendar "{APPLE_CALENDAR_NAME}"
  else
    set targetCal to first calendar whose writable is true
  end if
  tell targetCal
    make new event with properties {{summary:"{safe_title}", start date:startDate, end date:endDate, description:"{safe_notes}"}}
  end tell
  return name of targetCal
end tell'''
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=30, check=False
        )
    except subprocess.TimeoutExpired:
        message = (
            "Apple Calendar sync timed out — this usually means macOS is showing a "
            "permission dialog ('would like to add to your Calendar'). The event is safe "
            "in the local calendar; approve the dialog and ask me to create it again."
        )
        _record_apple_calendar_health(False, message)
        return message
    except OSError as exc:
        message = f"Apple Calendar sync FAILED ({exc}) — the event is still in the local calendar."
        _record_apple_calendar_health(False, message)
        return message
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[:120]
        message = (
            f"Apple Calendar sync FAILED ({detail}) — the event is still in the local "
            "calendar. If this is a permissions error, allow your terminal to control "
            "Calendar in System Settings > Privacy & Security > Automation."
        )
        _record_apple_calendar_health(False, message)
        return message
    used = (result.stdout or "").strip() or APPLE_CALENDAR_NAME
    _record_apple_calendar_health(True, f"Last write succeeded (calendar '{used}').")
    return f"Also added to Apple Calendar (calendar '{used}')."


def _google_event_body(
    title: str, start: str, end: str, attendees: str = "", notes: str = ""
) -> dict:
    """Map calendar fields to Google Calendar's event shape."""

    def rfc3339(value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.isoformat()

    body = {
        "summary": title,
        "start": {"dateTime": rfc3339(start)},
        "end": {"dateTime": rfc3339(end)},
    }
    if notes:
        body["description"] = notes
    emails = [parseaddr(item.strip())[1] for item in attendees.split(",")]
    emails = [email for email in emails if "@" in email]
    if emails:
        body["attendees"] = [{"email": email} for email in emails]
    return body


def probe_google_calendar(home: Path, calendar_id: str = "primary") -> None:
    """Verify cached OAuth access to a calendar without reading event data."""
    try:
        import google_auth_httplib2
        import httplib2
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError as exc:
        raise RuntimeError(
            "Google Calendar support is not installed; install with "
            "pip install -e '.[gcal]'"
        ) from exc

    token_path = home / "token.json"
    if not token_path.exists():
        raise RuntimeError(
            "Google Calendar is not authorized; complete OAuth with "
            f"{home / 'credentials.json'} and try again"
        )

    reauthorize = (
        "Google Calendar OAuth token is invalid; reauthorize with "
        f"{home / 'credentials.json'}"
    )
    try:
        credentials = Credentials.from_authorized_user_file(
            str(token_path), scopes=[GOOGLE_CALENDAR_SCOPE]
        )
    except Exception:
        raise RuntimeError(reauthorize) from None

    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            token_path.write_text(credentials.to_json(), encoding="utf-8")
        except Exception:
            raise RuntimeError(reauthorize) from None
    if not credentials.valid:
        raise RuntimeError(reauthorize)

    try:
        bounded_http = httplib2.Http(timeout=GOOGLE_CALENDAR_TIMEOUT)
        authorized_http = google_auth_httplib2.AuthorizedHttp(
            credentials, http=bounded_http
        )
        service = build(
            "calendar",
            "v3",
            http=authorized_http,
            cache_discovery=False,
            static_discovery=True,
        )
        (
            service.events()
            .list(calendarId=calendar_id, maxResults=1, fields="kind")
            .execute(num_retries=0)
        )
    except HttpError as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        reasons: set[str] = set()
        try:
            content = exc.content.decode() if isinstance(exc.content, bytes) else exc.content
            payload = json.loads(content)
            reasons = {
                item.get("reason", "")
                for item in payload.get("error", {}).get("errors", [])
                if isinstance(item, dict)
            }
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            pass
        if status == 401 or (
            status == 403
            and reasons.intersection({"authError", "insufficientPermissions"})
        ):
            raise RuntimeError(reauthorize) from None
        detail = (str(exc).strip() or type(exc).__name__)[:160]
        raise RuntimeError(f"Google Calendar probe failed ({detail})") from None
    except Exception as exc:
        detail = (str(exc).strip() or type(exc).__name__)[:160]
        raise RuntimeError(f"Google Calendar probe failed ({detail})") from None


def sync_to_google_calendar(
    title: str,
    start: str,
    end: str,
    attendees: str = "",
    notes: str = "",
    calendar_id: str = "primary",
    home: Path | None = None,
) -> str:
    """Create one Google Calendar event without changing the local-first contract."""
    try:
        import google.auth
        import google_auth_httplib2
        import httplib2
        from googleapiclient.discovery import build
    except ImportError:
        return (
            "Google Calendar sync FAILED (support is not installed; "
            "install with pip install -e '.[gcal]') — the event is still in the "
            "local calendar."
        )

    try:
        credentials = None
        if home is not None:
            try:
                from google.auth.transport.requests import Request
                from google.oauth2.credentials import Credentials
                from google_auth_oauthlib.flow import InstalledAppFlow
            except ImportError:
                return (
                    "Google Calendar sync FAILED (support is not installed; "
                    "install with pip install -e '.[gcal]') — the event is still in the "
                    "local calendar."
                )

            token_path = home / "token.json"
            creds_path = home / "credentials.json"

            if token_path.exists():
                try:
                    credentials = Credentials.from_authorized_user_file(
                        str(token_path), scopes=[GOOGLE_CALENDAR_SCOPE]
                    )
                except Exception:
                    credentials = None

            if credentials and credentials.expired and credentials.refresh_token:
                try:
                    credentials.refresh(Request())
                    token_path.parent.mkdir(parents=True, exist_ok=True)
                    token_path.write_text(credentials.to_json(), encoding="utf-8")
                except Exception:
                    credentials = None

            if not credentials or not credentials.valid:
                if not creds_path.exists():
                    root_creds = Path("credentials.json")
                    if root_creds.exists():
                        creds_path = root_creds
                    else:
                        return (
                            "Google Calendar sync FAILED (credentials.json not found in "
                            f"{home / 'credentials.json'}; download OAuth 2.0 Client ID "
                            "credentials from Google Cloud Console) — the event is still in the local calendar."
                        )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(creds_path), scopes=[GOOGLE_CALENDAR_SCOPE]
                )
                credentials = flow.run_local_server(port=0)
                token_path.parent.mkdir(parents=True, exist_ok=True)
                token_path.write_text(credentials.to_json(), encoding="utf-8")
        else:
            credentials, _ = google.auth.default(scopes=[GOOGLE_CALENDAR_SCOPE])

        bounded_http = httplib2.Http(timeout=GOOGLE_CALENDAR_TIMEOUT)
        authorized_http = google_auth_httplib2.AuthorizedHttp(
            credentials, http=bounded_http
        )
        service = build(
            "calendar",
            "v3",
            http=authorized_http,
            cache_discovery=False,
            static_discovery=True,
        )
        (
            service.events()
            .insert(
                calendarId=calendar_id,
                body=_google_event_body(title, start, end, attendees, notes),
                sendUpdates="none",
            )
            .execute(num_retries=0)
        )
    except Exception as exc:
        detail = (str(exc).strip() or type(exc).__name__)[:160]
        return (
            f"Google Calendar sync FAILED ({detail}) — the event is still in the "
            "local calendar."
        )
    return (
        f"Also added to Google Calendar (calendar '{calendar_id}'; "
        "attendee notifications suppressed)."
    )
