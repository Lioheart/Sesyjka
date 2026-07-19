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
        board_id = self.repository.save_board_game(
            {
                "nazwa": "Planszówka testowa",
                "typ": "Gra planszowa",
                "min_graczy": 2,
                "max_graczy": 4,
                "czas_min": 45,
                "czas_max": 90,
                "minimalny_wiek": 12,
                "cena": "149,90",
                "status_gra": "Grane",
                "status_kolekcja": "W kolekcji",
            }
        )
        self.assertEqual(self.repository.board_games()[0]["id"], board_id)
        stats = self.repository.statistics()
        self.assertEqual(stats["counts"]["Sesje"], 1)
        self.assertEqual(stats["counts"]["Pozycje RPG"], 1)
        self.assertEqual(stats["counts"]["Planszówki/Karcianki"], 1)
        self.assertEqual(stats["counts"]["Wartość pozycji"], "299,70 PLN")
        self.assertEqual(
            stats["charts"]["Planszówki/Karcianki"]["items"],
            [("Planszówki", 1), ("Karcianki", 0)],
        )
        self.assertEqual(stats["charts"]["Sesje"]["items"], [("2026", 1)])
        self.assertEqual(stats["charts"]["Pozycje RPG"]["items"], [("System Testowy", 1)])
        self.assertEqual(stats["charts"]["Wydawcy"]["items"], [("Test Publisher", 1)])

        self.repository.delete_session(session_id)
        self.assertEqual(self.repository.sessions(), [])


    def test_publisher_website_is_exposed_as_clickable_http_uri(self) -> None:
        self.repository.save_publisher(
            {"nazwa": "Wydawca WWW", "strona": "example.org/katalog"}
        )
        record = self.repository.publishers()[0]
        self.assertEqual(record["strona"], "example.org/katalog")
        self.assertEqual(record["strona_uri"], "https://example.org/katalog")

    def test_board_game_publisher_relation_and_rename_are_preserved(self) -> None:
        publisher_id = self.repository.save_publisher({"nazwa": "Stary wydawca"})
        board_id = self.repository.save_board_game(
            {
                "nazwa": "Gra powiązana",
                "wydawca_id": publisher_id,
            }
        )
        record = next(item for item in self.repository.board_games() if item["id"] == board_id)
        self.assertEqual(record["wydawca_id"], publisher_id)
        self.assertEqual(record["wydawca"], "Stary wydawca")

        with self.assertRaisesRegex(ValueError, "gry planszowe"):
            self.repository.delete_publisher(publisher_id)

        self.repository.save_publisher({"nazwa": "Nowy wydawca"}, publisher_id)
        record = next(item for item in self.repository.board_games() if item["id"] == board_id)
        self.assertEqual(record["wydawca"], "Nowy wydawca")
        with sqlite3.connect(self.root / "planszowe.db") as connection:
            stored = connection.execute(
                "SELECT wydawca_id, wydawca, notatki FROM planszowe WHERE id=?",
                (board_id,),
            ).fetchone()
        self.assertEqual(stored[0], publisher_id)
        self.assertEqual(stored[1], "Nowy wydawca")
        self.assertIsNone(stored[2])

    def test_legacy_board_game_publisher_name_is_migrated_to_identifier(self) -> None:
        legacy_root = self.root / "legacy-board-games"
        legacy_root.mkdir()
        with sqlite3.connect(legacy_root / "wydawcy.db") as connection:
            connection.execute(
                "CREATE TABLE wydawcy (id INTEGER PRIMARY KEY, nazwa TEXT NOT NULL, strona TEXT, kraj TEXT)"
            )
            connection.execute(
                "INSERT INTO wydawcy (id, nazwa) VALUES (7, 'Wydawca legacy')"
            )
        with sqlite3.connect(legacy_root / "planszowe.db") as connection:
            connection.execute(
                """
                CREATE TABLE planszowe (
                    id INTEGER PRIMARY KEY,
                    nazwa TEXT NOT NULL,
                    typ TEXT NOT NULL DEFAULT 'Gra planszowa',
                    min_graczy INTEGER NOT NULL DEFAULT 1,
                    max_graczy INTEGER NOT NULL DEFAULT 1,
                    czas_min INTEGER,
                    czas_max INTEGER,
                    minimalny_wiek INTEGER,
                    cena REAL,
                    waluta TEXT DEFAULT 'PLN',
                    status_gra TEXT DEFAULT 'Nie grane',
                    status_kolekcja TEXT DEFAULT 'W kolekcji',
                    wydawca TEXT,
                    rok_wydania INTEGER,
                    notatki TEXT
                )
                """
            )
            connection.execute(
                "INSERT INTO planszowe (id, nazwa, wydawca, notatki) VALUES (1, 'Legacy', 'wydawca LEGACY', 'zachowaj')"
            )

        databases = DatabaseManager(legacy_root)
        databases.initialize()
        repository = Repository(databases)
        record = repository.board_games()[0]
        self.assertEqual(record["wydawca_id"], 7)
        self.assertEqual(record["wydawca"], "Wydawca legacy")
        with sqlite3.connect(legacy_root / "planszowe.db") as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(planszowe)")}
            stored = connection.execute(
                "SELECT wydawca_id, wydawca, notatki FROM planszowe WHERE id=1"
            ).fetchone()
        self.assertIn("wydawca_id", columns)
        self.assertEqual(stored, (7, "wydawca LEGACY", "zachowaj"))

    def test_editing_game_system_without_hidden_fields_preserves_legacy_values(self) -> None:
        publisher_id = self.repository.save_publisher({"nazwa": "Legacy"})
        system_id = self.repository.save_game_system(
            {
                "nazwa": "System przed edycją",
                "wydawca_id": publisher_id,
                "jezyk": "PL",
                "notatki": "Stare notatki",
            }
        )
        self.repository.save_game_system(
            {"nazwa": "System po edycji", "notatki": "Nowe notatki"},
            system_id,
        )
        record = next(item for item in self.repository.game_systems() if item["id"] == system_id)
        self.assertEqual(record["wydawca_id"], publisher_id)
        self.assertEqual(record["jezyk"], "PL")
        self.assertEqual(record["notatki"], "Nowe notatki")

    def test_export_zip_contains_databases(self) -> None:
        destination = self.root / "export.zip"
        result = self.databases.export_zip(destination)
        self.assertEqual(result, destination)
        with zipfile.ZipFile(result) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"systemy_rpg.db", "sesje_rpg.db", "gracze.db", "wydawcy.db", "planszowe.db"},
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
            {"systemy_rpg.db", "sesje_rpg.db", "gracze.db", "wydawcy.db", "planszowe.db"},
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

    def test_group_must_belong_to_same_game_system(self) -> None:
        first_system = self.repository.save_game_system({"nazwa": "Pierwszy"})
        second_system = self.repository.save_game_system({"nazwa": "Drugi"})
        group_id = self.repository.save_system(
            {
                "nazwa": "Grupa pierwszego systemu",
                "typ": "Grupa",
                "system_gry_id": first_system,
            }
        )
        with self.assertRaisesRegex(ValueError, "tego samego systemu RPG"):
            self.repository.save_system(
                {
                    "nazwa": "Suplement",
                    "typ": "Suplement",
                    "system_gry_id": second_system,
                    "system_glowny_id": group_id,
                }
            )

    def test_only_group_records_can_be_selected_as_parent(self) -> None:
        game_system_id = self.repository.save_game_system({"nazwa": "System"})
        main_book_id = self.repository.save_system(
            {
                "nazwa": "Podręcznik główny",
                "typ": "Podręcznik Główny",
                "system_gry_id": game_system_id,
            }
        )
        with self.assertRaisesRegex(ValueError, "wyłącznie pozycję typu Grupa"):
            self.repository.save_system(
                {
                    "nazwa": "Pozycja podrzędna",
                    "typ": "Inne",
                    "system_gry_id": game_system_id,
                    "system_glowny_id": main_book_id,
                }
            )

    def test_group_can_contain_rpg_positions(self) -> None:
        game_system_id = self.repository.save_game_system({"nazwa": "System"})
        group_id = self.repository.save_system(
            {
                "nazwa": "Karty i pomoce",
                "typ": "Grupa",
                "system_gry_id": game_system_id,
            }
        )
        child_id = self.repository.save_system(
            {
                "nazwa": "Karty czarów",
                "typ": "Inne",
                "system_gry_id": game_system_id,
                "system_glowny_id": group_id,
            }
        )
        child = next(item for item in self.repository.systems() if item["id"] == child_id)
        self.assertEqual(child["system_glowny_id"], group_id)
        self.assertEqual(child["system_glowny_nazwa"], "Karty i pomoce")

    def test_group_cannot_be_converted_while_it_contains_positions(self) -> None:
        game_system_id = self.repository.save_game_system({"nazwa": "System"})
        group_id = self.repository.save_system(
            {
                "nazwa": "Grupa",
                "typ": "Grupa",
                "system_gry_id": game_system_id,
            }
        )
        self.repository.save_system(
            {
                "nazwa": "Pozycja",
                "typ": "Inne",
                "system_gry_id": game_system_id,
                "system_glowny_id": group_id,
            }
        )
        with self.assertRaisesRegex(ValueError, "Nie można zmienić typu grupy"):
            self.repository.save_system(
                {
                    "nazwa": "Grupa",
                    "typ": "Inne",
                    "system_gry_id": game_system_id,
                },
                group_id,
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
                "status_kolekcja": "Sprzedane",
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

    def test_board_game_crud_and_validation(self) -> None:
        record_id = self.repository.save_board_game(
            {
                "nazwa": "Karty testowe",
                "typ": "Gra karciana",
                "min_graczy": "2",
                "max_graczy": "6",
                "czas_min": "20",
                "czas_max": "40",
                "minimalny_wiek": "8",
                "cena": "59,99",
                "waluta": "PLN",
                "status_gra": "Nie grane",
                "status_kolekcja": "W kolekcji",
            }
        )
        record = self.repository.board_games()[0]
        self.assertEqual(record["id"], record_id)
        self.assertEqual(record["liczba_graczy_tekst"], "2-6")
        self.assertEqual(record["czas_tekst"], "20-40 min")
        self.assertEqual(record["cena_tekst"], "59.99 PLN")
        with self.assertRaisesRegex(ValueError, "Minimalna liczba graczy"):
            self.repository.save_board_game(
                {"nazwa": "Błędna", "min_graczy": 5, "max_graczy": 2}
            )
        self.repository.delete_board_game(record_id)
        self.assertEqual(self.repository.board_games(), [])

    def test_calendar_exports_include_session_details(self) -> None:
        player_id = self.repository.save_player({"nick": "Kalendarzowy"})
        system_id = self.repository.save_game_system({"nazwa": "System kalendarza"})
        self.repository.save_session(
            {
                "data_sesji": "2026-07-20",
                "system_id": system_id,
                "player_ids": [player_id],
                "tryb_gry": "Online",
                "tytul_przygody": "Test ICS",
                "notatka": "Opis wydarzenia",
            }
        )
        ics = self.repository.export_sessions_ics(self.root / "sesje.ics")
        csv_path = self.repository.export_sessions_csv(self.root / "sesje.csv")
        ics_text = ics.read_text(encoding="utf-8")
        csv_text = csv_path.read_text(encoding="utf-8-sig")
        self.assertIn("BEGIN:VCALENDAR", ics_text)
        self.assertIn("DTSTART;VALUE=DATE:20260720", ics_text)
        self.assertIn("Sesja RPG: System kalendarza", ics_text)
        self.assertIn("Subject,Start Date", csv_text)
        self.assertIn("Sesja RPG: System kalendarza", csv_text)
        self.assertIn("07/20/2026", csv_text)

    def test_rpg_component_prices_are_summed_and_irrelevant_prices_cleared(self) -> None:
        game_system_id = self.repository.save_game_system({"nazwa": "System cen"})
        record_id = self.repository.save_system(
            {
                "nazwa": "Pakiet",
                "typ": "Podręcznik Główny",
                "system_gry_id": game_system_id,
                "fizyczny": True,
                "pdf": False,
                "vtt": "Foundry VTT",
                "cena_fiz": "100",
                "cena_pdf": "50",
                "cena_vtt": "25",
                "cena_zakupu": "999",
                "status_kolekcja": "W kolekcji",
                "cena_sprzedazy": "20",
            }
        )
        record = next(item for item in self.repository.systems() if item["id"] == record_id)
        self.assertEqual(record["cena_fiz"], 100.0)
        self.assertIsNone(record["cena_pdf"])
        self.assertEqual(record["cena_vtt"], 25.0)
        self.assertEqual(record["cena_zakupu"], 125.0)
        self.assertIsNone(record["cena_sprzedazy"])

    def test_guest_mode_accepts_original_four_database_set(self) -> None:
        guest = self.root / "legacy-guest"
        guest.mkdir()
        for filename in ("systemy_rpg.db", "sesje_rpg.db", "gracze.db", "wydawcy.db"):
            (guest / filename).write_bytes((self.root / filename).read_bytes())
        self.databases.enter_guest_mode(guest)
        self.assertEqual(self.repository.board_games(), [])

    def test_board_games_schema_is_kept_in_separate_database(self) -> None:
        for filename in ("systemy_rpg.db", "sesje_rpg.db", "gracze.db", "wydawcy.db"):
            with sqlite3.connect(self.root / filename) as connection:
                table = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='planszowe'"
                ).fetchone()
            self.assertIsNone(table, filename)
        with sqlite3.connect(self.root / "planszowe.db") as connection:
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='planszowe'"
            ).fetchone()
        self.assertIsNotNone(table)

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

    def test_multiple_supplement_subgroups_are_preserved_without_schema_change(self) -> None:
        game_system_id = self.repository.save_game_system({"nazwa": "System"})
        record_id = self.repository.save_system(
            {
                "nazwa": "Suplement",
                "typ": "Suplement",
                "system_gry_id": game_system_id,
                "typ_suplementu": "Bestiariusz | Moduł | Rozwinięcie zasad",
            }
        )
        record = next(item for item in self.repository.systems() if item["id"] == record_id)
        self.assertEqual(
            record["typ_suplementu"],
            "Bestiariusz | Moduł | Rozwinięcie zasad",
        )
        with self.databases.connect("systemy_rpg.db") as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(systemy_rpg)")}
        self.assertNotIn("podgrupy_suplementu", columns)

    def test_non_supplement_clears_subgroup_and_gpb_is_normalized_to_gbp(self) -> None:
        game_system_id = self.repository.save_game_system({"nazwa": "System"})
        record_id = self.repository.save_system(
            {
                "nazwa": "Podręcznik",
                "typ": "Podręcznik Główny",
                "system_gry_id": game_system_id,
                "typ_suplementu": "Bestiariusz",
                "waluta_zakupu": "gpb",
            }
        )
        record = next(item for item in self.repository.systems() if item["id"] == record_id)
        self.assertIsNone(record["typ_suplementu"])
        self.assertEqual(record["waluta_zakupu"], "GBP")


if __name__ == "__main__":
    unittest.main()
