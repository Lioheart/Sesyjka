from __future__ import annotations

import os
import re
import urllib.parse
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

GOOGLE_CALENDAR_URL = "https://calendar.google.com/calendar/render"
ICLOUD_CALENDAR_URL = "https://www.icloud.com/calendar/"


def session_summary(session: dict[str, Any]) -> str:
    system = str(session.get("system_nazwa") or "Bez systemu").strip()
    detail = str(session.get("tytul_przygody") or session.get("tytul_kampanii") or "").strip()
    if detail:
        return f"Sesja RPG: {system} - {detail}"
    return f"Sesja RPG: {system}"


def session_description(session: dict[str, Any]) -> str:
    details = [
        f"System: {session.get('system_nazwa') or ''}",
        f"Mistrz gry: {session.get('mg_nazwa') or 'Brak, sesja GM-less'}",
        f"Gracze: {session.get('gracze_nazwy') or ''}",
        f"Tryb: {session.get('tryb_gry') or ''}",
    ]
    if session.get("tytul_kampanii"):
        details.append(f"Kampania: {session['tytul_kampanii']}")
    if session.get("tytul_przygody"):
        details.append(f"Przygoda: {session['tytul_przygody']}")
    if session.get("notatka"):
        details.extend(("", str(session["notatka"])))
    return "\n".join(details)


def _event_dates(session: dict[str, Any]) -> tuple[str, str]:
    event_date = datetime.strptime(str(session["data_sesji"]), "%Y-%m-%d").date()
    return event_date.strftime("%Y%m%d"), (event_date + timedelta(days=1)).strftime("%Y%m%d")


def google_calendar_event_url(session: dict[str, Any]) -> str:
    start, end = _event_dates(session)
    params = {
        "action": "TEMPLATE",
        "text": session_summary(session),
        "dates": f"{start}/{end}",
        "details": session_description(session),
        "location": str(session.get("tryb_gry") or ""),
    }
    return f"{GOOGLE_CALENDAR_URL}?{urllib.parse.urlencode(params)}"


def open_google_calendar(session: dict[str, Any]) -> bool:
    return bool(webbrowser.open(google_calendar_event_url(session), new=2))


def open_icloud_calendar() -> bool:
    return bool(webbrowser.open(ICLOUD_CALENDAR_URL, new=2))


def downloads_dir() -> Path:
    """Zwróć katalog Downloads zgodnie z XDG, bez zależności od xdg-user-dir."""
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    user_dirs = config_home / "user-dirs.dirs"
    try:
        text = user_dirs.read_text(encoding="utf-8")
    except OSError:
        text = ""
    match = re.search(r'^XDG_DOWNLOAD_DIR="([^"]+)"', text, flags=re.MULTILINE)
    if match:
        value = match.group(1).replace("$HOME", str(Path.home()))
        path = Path(os.path.expandvars(value)).expanduser()
    else:
        path = Path.home() / "Downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_session_filename(session: dict[str, Any]) -> str:
    raw = f"sesyjka-{session.get('data_sesji') or 'sesja'}-{session.get('system_nazwa') or 'rpg'}"
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", raw, flags=re.UNICODE).strip("-._")
    return (cleaned or "sesyjka-sesja") + ".ics"
