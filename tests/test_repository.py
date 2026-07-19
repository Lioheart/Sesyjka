from __future__ import annotations

import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from sesyjka.database_manager import DatabaseManager, ReadOnlyDatabaseError
from sesyjka.repository import Repository


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.databases = DatabaseManager(self.root)
        self.databases.initialize()
        self.repository = Repository(self.databases)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_complete_crud_path(self) -> None:
        publisher_id = self.repository.save_publisher(
            {"nazwa": "Test Publisher", "kraj": "PL", "strona": "https://example.test"}
        )
        player_id = self.repository.save_player(
            {"nick": "Gracz", "imie_nazwisko": "Jan Test", "grupa": "A", "wazna": True}
        )
        self.repository.save_game_system(
            {"nazwa": "System Pomocniczy", "wydawca_id": publisher_id, "jezyk": "PL"}
        )
        game_system_id = self.repository.save_game_system(
            {"nazwa": "System Testowy", "wydawca_id": publisher_id, "jezyk": "PL"}
        )
        system_id = self.repository.save_system(
            {
                "nazwa": "Podręcznik testowy",
                "typ": "Podręcznik główny",
                "system_gry_id": game_system_id,
                "wydawca_id": publisher_id,
                "jezyk": "PL",
                "fizyczny": True,
                "pdf": True,
                "status_gra": "Grane",
                "status_kolekcja": "W kolekcji",
                "cena_fiz": "99,90",
                "cena_pdf": "49.90",
                "waluta_zakupu": "PLN",
                "rok_wydania": "2026",
            }
        )
        session_id = self.repository.save_session(
            {
                "data_sesji": "2026-07-18",
                "system_id": game_system_id,
                "mg_id": player_id,
                "player_ids": [player_id],
                "kampania": True,
                "jednostrzal": False,
                "tryb_gry": "Stacjonarnie",
                "tytul_kampanii": "Kampania",
                "tytul_przygody": "Przygoda",
                "notatka": "Notatka testowa",
            }
        )

        self.assertEqual(self.repository.publishers()[0]["id"], publisher_id)
        self.assertEqual(self.repository.players()[0]["id"], player_id)
        self.assertEqual(self.repository.systems()[0]["system_gry_nazwa"], "System Testowy")
        session = self.repository.sessions()[0]
        self.assertEqual(session["id"], session_id)
        self.assertEqual(session["notatka"], "Notatka testowa")
        self.assertEqual(session["system_id"], game_system_id)
        self.assertEqual(session["system_nazwa"], "System Testowy")
        self.assertEqual(session["gracze_nazwy"], "Gracz")
        stats = self.repository.statistics()
        self.assertEqual(stats["counts"]["Sesje"], 1)
        self.assertEqual(stats["counts"]["Pozycje RPG"], 1)
        self.assertEqual(stats["charts"]["Sesje"]["items"], [("2026", 1)])
        self.assertEqual(stats["charts"]["Pozycje RPG"]["items"], [("System Testowy", 1)])
        self.assertEqual(stats["charts"]["Wydawcy"]["items"], [("Test Publisher", 1)])

        self.repository.delete_session(session_id)
        self.assertEqual(self.repository.sessions(), [])

    def test_export_zip_contains_databases(self) -> None:
        destination = self.root / "export.zip"
        result = self.databases.export_zip(destination)
        self.assertEqual(result, destination)
        with zipfile.ZipFile(result) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"systemy_rpg.db", "sesje_rpg.db", "gracze.db", "wydawcy.db"},
            )

    def test_guest_mode_blocks_writes(self) -> None:
        guest = self.root / "guest"
        guest.mkdir()
        for filename in ("systemy_rpg.db", "sesje_rpg.db", "gracze.db", "wydawcy.db"):
            (guest / filename).write_bytes((self.root / filename).read_bytes())
        self.databases.enter_guest_mode(guest)
        with self.assertRaises(ReadOnlyDatabaseError):
            self.repository.save_publisher({"nazwa": "Niedozwolone"})
        with self.databases.connect("wydawcy.db") as connection:
            with self.assertRaises(Exception):
                connection.execute("INSERT INTO wydawcy (id, nazwa) VALUES (99, 'Niedozwolone')")

    def test_session_without_players_is_rejected(self) -> None:
        game_system_id = self.repository.save_game_system({"nazwa": "System"})
        with self.assertRaisesRegex(ValueError, "co najmniej jednego gracza"):
            self.repository.save_session(
                {
                    "data_sesji": "2026-07-18",
                    "system_id": game_system_id,
                    "player_ids": [],
                }
            )

    def test_session_uses_game_system_name_not_book_name(self) -> None:
        player_id = self.repository.save_player({"nick": "Gracz"})
        first_game_id = self.repository.save_game_system({"nazwa": "Pierwszy system"})
        selected_game_id = self.repository.save_game_system({"nazwa": "Właściwy system"})
        book_id = self.repository.save_system(
            {
                "nazwa": "Nazwa suplementu",
                "typ": "Suplement",
                "system_gry_id": first_game_id,
            }
        )
        self.assertNotEqual(book_id, selected_game_id)
        self.repository.save_session(
            {
                "data_sesji": "2026-07-18",
                "system_id": selected_game_id,
                "player_ids": [player_id],
            }
        )
        session = self.repository.sessions()[0]
        self.assertEqual(session["system_nazwa"], "Właściwy system")
        self.assertNotEqual(session["system_nazwa"], "Nazwa suplementu")

    def test_game_system_delete_is_blocked_when_positions_are_linked(self) -> None:
        game_system_id = self.repository.save_game_system({"nazwa": "System"})
        self.repository.save_system(
            {
                "nazwa": "Podręcznik",
                "typ": "Podręcznik Główny",
                "system_gry_id": game_system_id,
            }
        )
        with self.assertRaisesRegex(ValueError, "podręczniki lub suplementy"):
            self.repository.delete_game_system(game_system_id)

    def test_empty_game_system_can_be_deleted(self) -> None:
        game_system_id = self.repository.save_game_system({"nazwa": "System"})
        self.repository.delete_game_system(game_system_id)
        self.assertEqual(self.repository.game_systems(), [])

    def test_invalid_session_date_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "RRRR-MM-DD"):
            self.repository.save_session({"data_sesji": "18.07.2026", "system_id": 1})

    def test_export_folder_contains_all_databases(self) -> None:
        destination = self.root / "folder-export"
        result = self.databases.export_folder(destination)
        self.assertEqual(result, destination)
        self.assertEqual(
            {path.name for path in destination.iterdir()},
            {"systemy_rpg.db", "sesje_rpg.db", "gracze.db", "wydawcy.db"},
        )

    def test_import_validation_rejects_database_with_wrong_schema(self) -> None:
        invalid = self.root / "invalid-import"
        invalid.mkdir()
        with sqlite3.connect(invalid / "gracze.db") as connection:
            connection.execute("CREATE TABLE nie_gracze (id INTEGER PRIMARY KEY)")
        with self.assertRaisesRegex(ValueError, "wymaganej tabeli gracze"):
            self.databases.inspect_import_source(invalid)

    def test_delete_player_is_blocked_when_linked_to_session(self) -> None:
        player_id = self.repository.save_player({"nick": "Powiązany"})
        system_id = self.repository.save_game_system({"nazwa": "System"})
        self.repository.save_session(
            {
                "data_sesji": "2026-07-19",
                "system_id": system_id,
                "mg_id": player_id,
                "player_ids": [player_id],
            }
        )
        with self.assertRaisesRegex(ValueError, "powiązanego z zapisanymi sesjami"):
            self.repository.delete_player(player_id)

    def test_delete_publisher_is_blocked_when_linked(self) -> None:
        publisher_id = self.repository.save_publisher({"nazwa": "Wydawca"})
        system_id = self.repository.save_game_system(
            {"nazwa": "System", "wydawca_id": publisher_id}
        )
        self.repository.save_system(
            {
                "nazwa": "Podręcznik",
                "typ": "Podręcznik Główny",
                "system_gry_id": system_id,
                "wydawca_id": publisher_id,
            }
        )
        with self.assertRaisesRegex(ValueError, "używanego przez systemy"):
            self.repository.delete_publisher(publisher_id)

    def test_parent_book_must_belong_to_same_game_system(self) -> None:
        first_system = self.repository.save_game_system({"nazwa": "Pierwszy"})
        second_system = self.repository.save_game_system({"nazwa": "Drugi"})
        parent_id = self.repository.save_system(
            {
                "nazwa": "Podręcznik",
                "typ": "Podręcznik Główny",
                "system_gry_id": first_system,
            }
        )
        with self.assertRaisesRegex(ValueError, "tego samego systemu RPG"):
            self.repository.save_system(
                {
                    "nazwa": "Suplement",
                    "typ": "Suplement",
                    "system_gry_id": second_system,
                    "system_glowny_id": parent_id,
                }
            )

    def test_system_prices_year_and_isbn_are_preserved(self) -> None:
        system_id = self.repository.save_game_system({"nazwa": "System"})
        record_id = self.repository.save_system(
            {
                "nazwa": "Podręcznik",
                "typ": "Podręcznik Główny",
                "system_gry_id": system_id,
                "cena_zakupu": "120,50",
                "waluta_zakupu": "PLN",
                "cena_sprzedazy": "90.00",
                "waluta_sprzedazy": "PLN",
                "rok_wydania": "2024",
                "isbn": "978-0-00-000000-0",
            }
        )
        record = next(item for item in self.repository.systems() if item["id"] == record_id)
        self.assertEqual(record["cena_zakupu"], 120.5)
        self.assertEqual(record["cena_sprzedazy"], 90.0)
        self.assertEqual(record["rok_wydania"], 2024)
        self.assertEqual(record["isbn"], "978-0-00-000000-0")

    def test_schema_update_creates_backup_before_migration(self) -> None:
        legacy_root = self.root / "legacy"
        legacy_root.mkdir()
        with sqlite3.connect(legacy_root / "gracze.db") as connection:
            connection.execute(
                "CREATE TABLE gracze (id INTEGER PRIMARY KEY, nick TEXT NOT NULL)"
            )
            connection.execute("INSERT INTO gracze (id, nick) VALUES (1, 'Stary gracz')")
        manager = DatabaseManager(legacy_root)
        manager.initialize()
        self.assertIsNotNone(manager.last_schema_backup)
        assert manager.last_schema_backup is not None
        self.assertTrue((manager.last_schema_backup / "gracze.db").is_file())
        with manager.connect("gracze.db") as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(gracze)")}
            count = connection.execute("SELECT COUNT(*) FROM gracze").fetchone()[0]
        self.assertIn("grupa", columns)
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
