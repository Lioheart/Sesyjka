from __future__ import annotations

import tempfile
import unittest
import urllib.parse
from pathlib import Path

from sesyjka.calendar_integration import (
    google_calendar_event_url,
    safe_session_filename,
    session_description,
    session_summary,
)
from sesyjka.database_manager import DatabaseManager
from sesyjka.repository import Repository


class CalendarIntegrationTests(unittest.TestCase):
    def sample_session(self) -> dict[str, object]:
        return {
            "id": 7,
            "data_sesji": "2026-08-20",
            "system_nazwa": "D&D 5e",
            "mg_nazwa": "MG",
            "gracze_nazwy": "Ala, Bob",
            "tryb_gry": "Stacjonarnie",
            "tytul_kampanii": "Klątwa Strahda",
            "tytul_przygody": "Zamek Ravenloft",
            "notatka": "Przynieść kości.",
        }

    def test_google_calendar_url_prefills_all_day_event(self) -> None:
        session = self.sample_session()
        url = google_calendar_event_url(session)
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "calendar.google.com")
        self.assertEqual(query["action"], ["TEMPLATE"])
        self.assertEqual(query["dates"], ["20260820/20260821"])
        self.assertIn("D&D 5e", query["text"][0])
        self.assertIn("Ala, Bob", query["details"][0])

    def test_summary_and_description_include_session_context(self) -> None:
        session = self.sample_session()
        self.assertIn("Zamek Ravenloft", session_summary(session))
        description = session_description(session)
        self.assertIn("Mistrz gry: MG", description)
        self.assertIn("Przynieść kości.", description)

    def test_safe_ics_filename(self) -> None:
        name = safe_session_filename(self.sample_session())
        self.assertTrue(name.endswith(".ics"))
        self.assertNotIn(" ", name)
        self.assertNotIn("/", name)

    def test_single_session_ics_contains_one_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = DatabaseManager(root)
            db.initialize()
            repo = Repository(db)
            destination = repo.export_session_ics(self.sample_session(), root / "event.ics")
            text = destination.read_text(encoding="utf-8")
            self.assertEqual(text.count("BEGIN:VEVENT"), 1)
            self.assertIn("DTSTART;VALUE=DATE:20260820", text)
            self.assertIn("DTEND;VALUE=DATE:20260821", text)
            self.assertIn("Zamek Ravenloft", text)


if __name__ == "__main__":
    unittest.main()
