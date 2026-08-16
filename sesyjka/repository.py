from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from pathlib import Path
import uuid
from typing import Any
from urllib.parse import urlsplit

from .database_manager import DatabaseManager
from .calendar_integration import session_description, session_summary


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _website_uri(value: Any) -> str:
    """Zwróć bezpieczny adres HTTP(S) do otwarcia w przeglądarce."""
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = text if "://" in text else f"https://{text}"
    parsed = urlsplit(candidate)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return ""
    return candidate


class Repository:
    def __init__(self, databases: DatabaseManager) -> None:
        self.db = databases

    def publishers(self) -> list[dict[str, Any]]:
        rows = self.db.table_rows(
            "wydawcy.db",
            "SELECT id, nazwa, strona, kraj FROM wydawcy ORDER BY nazwa COLLATE NOCASE",
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["strona_uri"] = _website_uri(item.get("strona"))
            result.append(item)
        return result

    def save_publisher(self, values: dict[str, Any], record_id: int | None = None) -> int:
        name = str(values.get("nazwa", "")).strip()
        if not name:
            raise ValueError("Nazwa wydawcy jest wymagana.")
        with self.db.connect("wydawcy.db", write=True) as connection:
            if record_id is None:
                record_id = self.db.next_id("wydawcy.db", "wydawcy")
                connection.execute(
                    "INSERT INTO wydawcy (id, nazwa, strona, kraj) VALUES (?, ?, ?, ?)",
                    (record_id, name, _clean(values.get("strona")), _clean(values.get("kraj"))),
                )
            else:
                connection.execute(
                    "UPDATE wydawcy SET nazwa=?, strona=?, kraj=? WHERE id=?",
                    (name, _clean(values.get("strona")), _clean(values.get("kraj")), record_id),
                )

        # planszowe.db przechowuje identyfikator relacji oraz tekstową nazwę
        # kompatybilną z wersjami 0.8.0-0.8.3. Synchronizacja nazwy pozwala
        # starszym wydaniom nadal poprawnie wyświetlić rekord.
        if self.db.has_active_database("planszowe.db"):
            with self.db.connect("planszowe.db", write=True) as connection:
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(planszowe)")
                }
                if {"wydawca_id", "wydawca"}.issubset(columns):
                    connection.execute(
                        "UPDATE planszowe SET wydawca=? WHERE wydawca_id=?",
                        (name, record_id),
                    )
        return record_id

    def delete_publisher(self, record_id: int) -> None:
        linked_positions = int(
            self.db.table_rows(
                "systemy_rpg.db",
                "SELECT COUNT(*) AS count FROM systemy_rpg WHERE wydawca_id=?",
                (record_id,),
            )[0]["count"]
        )
        linked_systems = int(
            self.db.table_rows(
                "systemy_rpg.db",
                "SELECT COUNT(*) AS count FROM systemy_gry WHERE wydawca_id=?",
                (record_id,),
            )[0]["count"]
        )
        linked_board_games = 0
        if self.db.has_active_database("planszowe.db"):
            with self.db.connect("planszowe.db") as connection:
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(planszowe)")
                }
                if "wydawca_id" in columns:
                    row = connection.execute(
                        "SELECT COUNT(*) AS count FROM planszowe WHERE wydawca_id=?",
                        (record_id,),
                    ).fetchone()
                    linked_board_games = int(row["count"] if row else 0)
        if linked_positions or linked_systems or linked_board_games:
            raise ValueError(
                "Nie można usunąć wydawcy używanego przez systemy, pozycje RPG "
                "albo gry planszowe i karciane."
            )
        with self.db.connect("wydawcy.db", write=True) as connection:
            connection.execute("DELETE FROM wydawcy WHERE id=?", (record_id,))

    def players(self) -> list[dict[str, Any]]:
        rows = self.db.table_rows(
            "gracze.db",
            """
            SELECT id, nick, imie_nazwisko, plec, social,
                   glowny_uzytkownik, wazna, grupa
            FROM gracze ORDER BY nick COLLATE NOCASE
            """,
        )
        return [dict(row) for row in rows]

    def save_player(self, values: dict[str, Any], record_id: int | None = None) -> int:
        nick = str(values.get("nick", "")).strip()
        if not nick:
            raise ValueError("Nick gracza jest wymagany.")
        payload = (
            nick,
            _clean(values.get("imie_nazwisko")),
            _clean(values.get("plec")),
            _clean(values.get("social")),
            int(bool(values.get("glowny_uzytkownik"))),
            int(bool(values.get("wazna"))),
            _clean(values.get("grupa")),
        )
        with self.db.connect("gracze.db", write=True) as connection:
            if record_id is None:
                record_id = self.db.next_id("gracze.db", "gracze")
                connection.execute(
                    """
                    INSERT INTO gracze
                    (id, nick, imie_nazwisko, plec, social, glowny_uzytkownik, wazna, grupa)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (record_id, *payload),
                )
            else:
                connection.execute(
                    """
                    UPDATE gracze SET nick=?, imie_nazwisko=?, plec=?, social=?,
                    glowny_uzytkownik=?, wazna=?, grupa=? WHERE id=?
                    """,
                    (*payload, record_id),
                )
        return record_id

    def delete_player(self, record_id: int) -> None:
        gm_sessions = int(
            self.db.table_rows(
                "sesje_rpg.db",
                "SELECT COUNT(*) AS count FROM sesje_rpg WHERE mg_id=?",
                (record_id,),
            )[0]["count"]
        )
        player_sessions = int(
            self.db.table_rows(
                "sesje_rpg.db",
                "SELECT COUNT(*) AS count FROM sesje_gracze WHERE gracz_id=?",
                (record_id,),
            )[0]["count"]
        )
        if gm_sessions or player_sessions:
            raise ValueError(
                "Nie można usunąć gracza powiązanego z zapisanymi sesjami."
            )
        with self.db.connect("gracze.db", write=True) as connection:
            connection.execute("DELETE FROM gracze WHERE id=?", (record_id,))

    def game_systems(self) -> list[dict[str, Any]]:
        publishers = {row["id"]: row["nazwa"] for row in self.publishers()}
        rows = self.db.table_rows(
            "systemy_rpg.db",
            "SELECT id, nazwa, wydawca_id, jezyk, notatki FROM systemy_gry ORDER BY nazwa COLLATE NOCASE",
        )
        counts = {
            int(row["system_gry_id"]): int(row["count"])
            for row in self.db.table_rows(
                "systemy_rpg.db",
                """
                SELECT system_gry_id, COUNT(*) AS count
                FROM systemy_rpg
                WHERE system_gry_id IS NOT NULL
                GROUP BY system_gry_id
                """,
            )
        }
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["wydawca_nazwa"] = publishers.get(item.get("wydawca_id"), "")
            item["liczba_pozycji"] = counts.get(int(item["id"]), 0)
            result.append(item)
        return result

    def save_game_system(self, values: dict[str, Any], record_id: int | None = None) -> int:
        name = str(values.get("nazwa", "")).strip()
        if not name:
            raise ValueError("Nazwa systemu gry jest wymagana.")

        existing: dict[str, Any] = {}
        if record_id is not None:
            rows = self.db.table_rows(
                "systemy_rpg.db",
                "SELECT wydawca_id, jezyk, notatki FROM systemy_gry WHERE id=?",
                (record_id,),
            )
            if not rows:
                raise ValueError("Edytowany system gry nie istnieje.")
            existing = dict(rows[0])

        # Interfejs 0.8.4 nie eksponuje wydawcy ani języka systemu gry.
        # Parametry pozostają obsługiwane w API, aby nie usuwać danych zapisanych
        # przez wcześniejsze wydania oraz zachować zgodność z bazą źródłową.
        publisher_id = (
            values.get("wydawca_id")
            if "wydawca_id" in values
            else existing.get("wydawca_id")
        )
        language = (
            _clean(values.get("jezyk"))
            if "jezyk" in values
            else existing.get("jezyk")
        )
        notes = (
            _clean(values.get("notatki"))
            if "notatki" in values
            else existing.get("notatki")
        )
        if publisher_id is not None:
            valid_publishers = {int(item["id"]) for item in self.publishers()}
            if int(publisher_id) not in valid_publishers:
                raise ValueError("Wybrany wydawca nie istnieje w bazie wydawców.")
        payload = (
            name,
            int(publisher_id) if publisher_id is not None else None,
            language,
            notes,
        )
        with self.db.connect("systemy_rpg.db", write=True) as connection:
            if record_id is None:
                cursor = connection.execute(
                    "INSERT INTO systemy_gry (nazwa, wydawca_id, jezyk, notatki) VALUES (?, ?, ?, ?)",
                    payload,
                )
                record_id = int(cursor.lastrowid)
            else:
                connection.execute(
                    "UPDATE systemy_gry SET nazwa=?, wydawca_id=?, jezyk=?, notatki=? WHERE id=?",
                    (*payload, record_id),
                )
        return record_id

    def delete_game_system(self, record_id: int) -> None:
        position_count = int(
            self.db.table_rows(
                "systemy_rpg.db",
                "SELECT COUNT(*) AS count FROM systemy_rpg WHERE system_gry_id=?",
                (record_id,),
            )[0]["count"]
        )
        if position_count:
            raise ValueError(
                "Nie można usunąć systemu, do którego są przypisane podręczniki lub suplementy."
            )
        session_count = int(
            self.db.table_rows(
                "sesje_rpg.db",
                "SELECT COUNT(*) AS count FROM sesje_rpg WHERE system_id=?",
                (record_id,),
            )[0]["count"]
        )
        if session_count:
            raise ValueError(
                "Nie można usunąć systemu używanego przez zapisane sesje."
            )
        with self.db.connect("systemy_rpg.db", write=True) as connection:
            connection.execute("DELETE FROM systemy_gry WHERE id=?", (record_id,))

    def systems(self) -> list[dict[str, Any]]:
        publishers = {row["id"]: row["nazwa"] for row in self.publishers()}
        game_systems = {row["id"]: row["nazwa"] for row in self.game_systems()}
        rows = self.db.table_rows(
            "systemy_rpg.db",
            """
            SELECT id, nazwa, typ, system_glowny_id, typ_suplementu, wydawca_id,
                   fizyczny, pdf, jezyk, status_gra, status_kolekcja,
                   cena_zakupu, waluta_zakupu, cena_sprzedazy, waluta_sprzedazy,
                   vtt, system_glowny_nazwa_custom, system_gry_id,
                   cena_fiz, cena_pdf, cena_vtt, rok_wydania, isbn
            FROM systemy_rpg ORDER BY nazwa COLLATE NOCASE
            """,
        )
        raw = [dict(row) for row in rows]
        names = {item["id"]: item["nazwa"] for item in raw}
        result: list[dict[str, Any]] = []
        for item in raw:
            item["wydawca_nazwa"] = publishers.get(item.get("wydawca_id"), "")
            item["system_gry_nazwa"] = game_systems.get(item.get("system_gry_id"), "")
            item["system_glowny_nazwa"] = (
                names.get(item.get("system_glowny_id"))
                or item.get("system_glowny_nazwa_custom")
                or ""
            )
            result.append(item)
        return result

    def save_system(self, values: dict[str, Any], record_id: int | None = None) -> int:
        name = str(values.get("nazwa", "")).strip()
        item_type = str(values.get("typ", "")).strip()
        if not name or not item_type:
            raise ValueError("Nazwa i typ pozycji są wymagane.")
        fields = (
            "nazwa", "typ", "system_glowny_id", "typ_suplementu", "wydawca_id",
            "fizyczny", "pdf", "jezyk", "status_gra", "status_kolekcja",
            "cena_zakupu", "waluta_zakupu", "cena_sprzedazy", "waluta_sprzedazy",
            "vtt", "system_glowny_nazwa_custom", "system_gry_id", "cena_fiz",
            "cena_pdf", "cena_vtt", "rok_wydania", "isbn",
        )
        allowed_types = {
            value.casefold(): value
            for value in ("Podręcznik Główny", "Suplement", "Inne", "Grupa")
        }
        canonical_type = allowed_types.get(item_type.casefold())
        if canonical_type is None:
            raise ValueError(
                "Typ pozycji musi być jednym z: Podręcznik Główny, Suplement, Inne, Grupa."
            )
        item_type = canonical_type

        normalized = dict(values)
        normalized["nazwa"] = name
        normalized["typ"] = item_type
        if item_type.casefold() == "suplement":
            supplement_values = [
                part.strip()
                for part in re.split(r"[;,|\n]+", str(normalized.get("typ_suplementu") or ""))
                if part.strip()
            ]
            normalized["typ_suplementu"] = " | ".join(dict.fromkeys(supplement_values))
        else:
            normalized["typ_suplementu"] = None

        for currency_key in ("waluta_zakupu", "waluta_sprzedazy"):
            currency_code = str(normalized.get(currency_key) or "").strip().upper()
            normalized[currency_key] = "GBP" if currency_code == "GPB" else currency_code

        game_system_id = normalized.get("system_gry_id")
        valid_game_system_ids = {int(item["id"]) for item in self.game_systems()}
        if game_system_id is None or int(game_system_id) not in valid_game_system_ids:
            raise ValueError("Przypisz pozycję do istniejącego systemu RPG.")
        normalized["system_gry_id"] = int(game_system_id)

        publisher_id = normalized.get("wydawca_id")
        if publisher_id is not None:
            valid_publishers = {int(item["id"]) for item in self.publishers()}
            if int(publisher_id) not in valid_publishers:
                raise ValueError("Wybrany wydawca nie istnieje w bazie wydawców.")
            normalized["wydawca_id"] = int(publisher_id)

        existing_record: dict[str, Any] | None = None
        if record_id is not None:
            existing_rows = self.db.table_rows(
                "systemy_rpg.db",
                "SELECT id, typ, system_gry_id FROM systemy_rpg WHERE id=?",
                (int(record_id),),
            )
            if existing_rows:
                existing_record = dict(existing_rows[0])

        child_count = 0
        if record_id is not None:
            child_count = int(
                self.db.table_rows(
                    "systemy_rpg.db",
                    "SELECT COUNT(*) AS count FROM systemy_rpg WHERE system_glowny_id=?",
                    (int(record_id),),
                )[0]["count"]
            )

        if (
            existing_record
            and str(existing_record.get("typ") or "").casefold() == "grupa"
            and item_type != "Grupa"
            and child_count
        ):
            raise ValueError(
                "Nie można zmienić typu grupy, dopóki są do niej przypisane pozycje."
            )
        if (
            existing_record
            and item_type == "Grupa"
            and child_count
            and existing_record.get("system_gry_id") is not None
            and int(existing_record["system_gry_id"]) != int(game_system_id)
        ):
            raise ValueError(
                "Nie można przenieść grupy do innego systemu RPG, dopóki zawiera pozycje."
            )

        parent_id = normalized.get("system_glowny_id")
        if item_type == "Grupa":
            normalized["system_glowny_id"] = None
        elif parent_id is not None:
            parent_id = int(parent_id)
            if record_id is not None and parent_id == int(record_id):
                raise ValueError("Pozycja nie może być własną grupą.")
            parent_rows = self.db.table_rows(
                "systemy_rpg.db",
                "SELECT id, typ, system_glowny_id, system_gry_id FROM systemy_rpg WHERE id=?",
                (parent_id,),
            )
            if not parent_rows:
                raise ValueError("Wybrana grupa nie istnieje.")
            parent = parent_rows[0]
            if str(parent["typ"] or "").casefold() != "grupa":
                raise ValueError("Jako grupę można wybrać wyłącznie pozycję typu Grupa.")
            if parent["system_gry_id"] is None or int(parent["system_gry_id"]) != int(game_system_id):
                raise ValueError("Grupa musi należeć do tego samego systemu RPG.")
            normalized["system_glowny_id"] = parent_id
        else:
            normalized["system_glowny_id"] = None
        for key in ("fizyczny", "pdf"):
            normalized[key] = int(bool(normalized.get(key)))
        normalized["vtt"] = _clean(normalized.get("vtt"))
        for key in ("cena_zakupu", "cena_sprzedazy", "cena_fiz", "cena_pdf", "cena_vtt"):
            value = normalized.get(key)
            if value in (None, ""):
                normalized[key] = None
            else:
                parsed = float(str(value).replace(",", "."))
                if parsed < 0:
                    raise ValueError("Ceny nie mogą być ujemne.")
                normalized[key] = parsed

        if not normalized["fizyczny"]:
            normalized["cena_fiz"] = None
        if not normalized["pdf"]:
            normalized["cena_pdf"] = None
        if not normalized["vtt"]:
            normalized["cena_vtt"] = None

        component_prices = [
            normalized.get("cena_fiz"),
            normalized.get("cena_pdf"),
            normalized.get("cena_vtt"),
        ]
        if any(value is not None for value in component_prices):
            normalized["cena_zakupu"] = round(
                sum(float(value or 0) for value in component_prices), 2
            )

        if str(normalized.get("status_kolekcja") or "") not in {"Na sprzedaż", "Sprzedane"}:
            normalized["cena_sprzedazy"] = None

        year = normalized.get("rok_wydania")
        normalized["rok_wydania"] = int(year) if year not in (None, "") else None
        payload = [_clean(normalized.get(field)) for field in fields]
        placeholders = ", ".join("?" for _ in fields)
        with self.db.connect("systemy_rpg.db", write=True) as connection:
            if record_id is None:
                record_id = self.db.next_id("systemy_rpg.db", "systemy_rpg")
                connection.execute(
                    f"INSERT INTO systemy_rpg (id, {', '.join(fields)}) VALUES (?, {placeholders})",
                    (record_id, *payload),
                )
            else:
                assignments = ", ".join(f"{field}=?" for field in fields)
                connection.execute(
                    f"UPDATE systemy_rpg SET {assignments} WHERE id=?",
                    (*payload, record_id),
                )
        return record_id

    def delete_system(self, record_id: int) -> None:
        if self.db.has_active_database("zasoby.db"):
            linked_resources = int(
                self.db.table_rows(
                    "zasoby.db",
                    "SELECT COUNT(*) AS count FROM zasoby WHERE pozycja_rpg_id=?",
                    (record_id,),
                )[0]["count"]
            )
            if linked_resources:
                raise ValueError(
                    "Nie można usunąć pozycji RPG, dopóki ma przypisane zasoby cyfrowe."
                )
        child_count = int(
            self.db.table_rows(
                "systemy_rpg.db",
                "SELECT COUNT(*) AS count FROM systemy_rpg WHERE system_glowny_id=?",
                (record_id,),
            )[0]["count"]
        )
        if child_count:
            raise ValueError(
                "Nie można usunąć grupy, do której przypisano pozycje."
            )
        with self.db.connect("systemy_rpg.db", write=True) as connection:
            connection.execute("DELETE FROM systemy_rpg WHERE id=?", (record_id,))

    def sessions(self) -> list[dict[str, Any]]:
        game_systems = {row["id"]: row["nazwa"] for row in self.game_systems()}
        positions = {row["id"]: row for row in self.systems()}
        players = {row["id"]: row["nick"] for row in self.players()}
        rows = self.db.table_rows(
            "sesje_rpg.db",
            """
            SELECT id, data_sesji, system_id, liczba_graczy, mg_id, kampania,
                   jednostrzal, tytul_kampanii, tytul_przygody, tryb_gry
            FROM sesje_rpg ORDER BY data_sesji DESC, id DESC
            """,
        )
        links = self.db.table_rows(
            "sesje_rpg.db",
            "SELECT sesja_id, gracz_id FROM sesje_gracze ORDER BY sesja_id, gracz_id",
        )
        notes = self.db.table_rows(
            "sesje_rpg.db",
            "SELECT sesja_id, tresc, data_modyfikacji FROM sesje_notatki",
        )
        player_ids: dict[int, list[int]] = {}
        for link in links:
            player_ids.setdefault(int(link["sesja_id"]), []).append(int(link["gracz_id"]))
        note_map = {int(row["sesja_id"]): str(row["tresc"]) for row in notes}
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            ids = player_ids.get(int(item["id"]), [])
            item["player_ids"] = ids
            item["gracze_nazwy"] = ", ".join(players.get(player_id, f"#{player_id}") for player_id in ids)

            stored_system_id = int(item["system_id"])
            resolved_system_id = stored_system_id
            system_name = game_systems.get(stored_system_id)
            if system_name is None and stored_system_id in positions:
                legacy_position = positions[stored_system_id]
                linked_id = legacy_position.get("system_gry_id")
                if linked_id in game_systems:
                    resolved_system_id = int(linked_id)
                    system_name = game_systems[resolved_system_id]
                else:
                    system_name = str(legacy_position.get("nazwa") or f"System ID {stored_system_id}")
            item["stored_system_id"] = stored_system_id
            item["system_id"] = resolved_system_id
            item["system_nazwa"] = system_name or f"System ID {stored_system_id}"
            item["mg_nazwa"] = "N/A" if item.get("mg_id") is None else players.get(item.get("mg_id"), "")
            item["notatka"] = note_map.get(int(item["id"]), "")
            result.append(item)
        return result

    def save_session(self, values: dict[str, Any], record_id: int | None = None) -> int:
        date = str(values.get("data_sesji", "")).strip()
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Data sesji musi mieć format RRRR-MM-DD.") from exc
        system_id = values.get("system_id")
        if not system_id:
            raise ValueError("Wybierz system RPG.")
        valid_system_ids = {int(item["id"]) for item in self.game_systems()}
        if int(system_id) not in valid_system_ids:
            raise ValueError("Wybrany system RPG nie istnieje w katalogu systemów.")
        selected_players = sorted({int(value) for value in values.get("player_ids", [])})
        if not selected_players:
            raise ValueError("Sesja musi mieć co najmniej jednego gracza.")
        valid_player_ids = {int(item["id"]) for item in self.players()}
        missing_players = [player_id for player_id in selected_players if player_id not in valid_player_ids]
        if missing_players:
            raise ValueError("Co najmniej jeden wybrany gracz nie istnieje już w bazie.")
        gm_id = values.get("mg_id") or None
        if gm_id is not None and int(gm_id) not in valid_player_ids:
            raise ValueError("Wybrany mistrz gry nie istnieje już w bazie graczy.")
        payload = (
            date,
            int(system_id),
            len(selected_players),
            int(gm_id) if gm_id is not None else None,
            int(bool(values.get("kampania"))),
            int(bool(values.get("jednostrzal"))),
            _clean(values.get("tytul_kampanii")),
            _clean(values.get("tytul_przygody")),
            _clean(values.get("tryb_gry")),
        )
        with self.db.connect("sesje_rpg.db", write=True) as connection:
            if record_id is None:
                record_id = self.db.next_id("sesje_rpg.db", "sesje_rpg")
                connection.execute(
                    """
                    INSERT INTO sesje_rpg
                    (id, data_sesji, system_id, liczba_graczy, mg_id, kampania,
                     jednostrzal, tytul_kampanii, tytul_przygody, tryb_gry)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (record_id, *payload),
                )
            else:
                connection.execute(
                    """
                    UPDATE sesje_rpg SET data_sesji=?, system_id=?, liczba_graczy=?,
                    mg_id=?, kampania=?, jednostrzal=?, tytul_kampanii=?,
                    tytul_przygody=?, tryb_gry=? WHERE id=?
                    """,
                    (*payload, record_id),
                )
                connection.execute("DELETE FROM sesje_gracze WHERE sesja_id=?", (record_id,))
            connection.executemany(
                "INSERT INTO sesje_gracze (sesja_id, gracz_id) VALUES (?, ?)",
                [(record_id, player_id) for player_id in selected_players],
            )
            note = str(values.get("notatka", "")).strip()
            if note:
                connection.execute(
                    """
                    INSERT INTO sesje_notatki (sesja_id, tresc, data_modyfikacji)
                    VALUES (?, ?, ?)
                    ON CONFLICT(sesja_id) DO UPDATE SET
                    tresc=excluded.tresc, data_modyfikacji=excluded.data_modyfikacji
                    """,
                    (record_id, note, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
            else:
                connection.execute("DELETE FROM sesje_notatki WHERE sesja_id=?", (record_id,))
        return record_id

    def delete_session(self, record_id: int) -> None:
        with self.db.connect("sesje_rpg.db", write=True) as connection:
            connection.execute("DELETE FROM sesje_rpg WHERE id=?", (record_id,))

    def board_games(self) -> list[dict[str, Any]]:
        if not self.db.has_active_database("planszowe.db"):
            return []
        publishers = {int(row["id"]): str(row["nazwa"]) for row in self.publishers()}
        rows = self.db.table_rows(
            "planszowe.db",
            """
            SELECT id, nazwa, typ, min_graczy, max_graczy, czas_min, czas_max,
                   minimalny_wiek, cena, waluta, status_gra, status_kolekcja,
                   wydawca_id, wydawca, rok_wydania
            FROM planszowe ORDER BY nazwa COLLATE NOCASE
            """,
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            publisher_id = item.get("wydawca_id")
            item["wydawca"] = (
                publishers.get(int(publisher_id), "")
                if publisher_id is not None
                else str(item.get("wydawca") or "")
            )
            minimum = int(item.get("min_graczy") or 1)
            maximum = int(item.get("max_graczy") or minimum)
            item["liczba_graczy_tekst"] = str(minimum) if minimum == maximum else f"{minimum}-{maximum}"
            time_min = item.get("czas_min")
            time_max = item.get("czas_max")
            if time_min is None and time_max is None:
                item["czas_tekst"] = ""
            elif time_max is None or int(time_max) == int(time_min or 0):
                item["czas_tekst"] = f"{int(time_min or time_max)} min"
            elif time_min is None:
                item["czas_tekst"] = f"do {int(time_max)} min"
            else:
                item["czas_tekst"] = f"{int(time_min)}-{int(time_max)} min"
            if item.get("cena") is None:
                item["cena_tekst"] = ""
            else:
                item["cena_tekst"] = f"{float(item['cena']):g} {item.get('waluta') or 'PLN'}"
            result.append(item)
        return result

    @staticmethod
    def _optional_nonnegative_int(value: Any, label: str) -> int | None:
        if value in (None, ""):
            return None
        try:
            parsed = int(str(value).strip())
        except ValueError as exc:
            raise ValueError(f"{label} musi być liczbą całkowitą.") from exc
        if parsed < 0:
            raise ValueError(f"{label} nie może być ujemne.")
        return parsed

    def save_board_game(self, values: dict[str, Any], record_id: int | None = None) -> int:
        name = str(values.get("nazwa", "")).strip()
        if not name:
            raise ValueError("Nazwa gry jest wymagana.")
        game_type = str(values.get("typ") or "Gra planszowa").strip()
        if game_type not in {"Gra planszowa", "Gra karciana"}:
            raise ValueError("Typ musi wskazywać grę planszową albo karcianą.")

        minimum_players = self._optional_nonnegative_int(values.get("min_graczy"), "Minimalna liczba graczy")
        maximum_players = self._optional_nonnegative_int(values.get("max_graczy"), "Maksymalna liczba graczy")
        minimum_players = minimum_players or 1
        maximum_players = maximum_players or minimum_players
        if minimum_players < 1 or maximum_players < 1:
            raise ValueError("Gra musi obsługiwać co najmniej jednego gracza.")
        if minimum_players > maximum_players:
            raise ValueError("Minimalna liczba graczy nie może przekraczać maksymalnej.")

        time_min = self._optional_nonnegative_int(values.get("czas_min"), "Minimalny czas rozgrywki")
        time_max = self._optional_nonnegative_int(values.get("czas_max"), "Maksymalny czas rozgrywki")
        if time_min is not None and time_max is not None and time_min > time_max:
            raise ValueError("Minimalny czas rozgrywki nie może przekraczać maksymalnego.")
        age = self._optional_nonnegative_int(values.get("minimalny_wiek"), "Minimalny wiek")
        year = self._optional_nonnegative_int(values.get("rok_wydania"), "Rok wydania")
        if year is not None and not 1000 <= year <= 9999:
            raise ValueError("Rok wydania musi mieć cztery cyfry.")

        price_value = values.get("cena")
        price: float | None
        if price_value in (None, ""):
            price = None
        else:
            try:
                price = float(str(price_value).replace(",", "."))
            except ValueError as exc:
                raise ValueError("Cena musi być liczbą.") from exc
            if price < 0:
                raise ValueError("Cena nie może być ujemna.")

        publishers = {int(item["id"]): str(item["nazwa"]) for item in self.publishers()}
        publisher_id = values.get("wydawca_id")
        legacy_publisher = _clean(values.get("wydawca"))
        if publisher_id is None and legacy_publisher:
            matching = [
                identifier
                for identifier, label in publishers.items()
                if label.casefold() == str(legacy_publisher).casefold()
            ]
            if matching:
                publisher_id = matching[0]
            else:
                raise ValueError("Wybierz wydawcę istniejącego w bazie wydawców.")
        if publisher_id is not None:
            publisher_id = int(publisher_id)
            if publisher_id not in publishers:
                raise ValueError("Wybrany wydawca nie istnieje w bazie wydawców.")
        publisher_name = publishers.get(publisher_id) if publisher_id is not None else None

        fields = (
            "nazwa", "typ", "min_graczy", "max_graczy", "czas_min", "czas_max",
            "minimalny_wiek", "cena", "waluta", "status_gra", "status_kolekcja",
            "wydawca_id", "wydawca", "rok_wydania",
        )
        normalized = {
            "nazwa": name,
            "typ": game_type,
            "min_graczy": minimum_players,
            "max_graczy": maximum_players,
            "czas_min": time_min,
            "czas_max": time_max,
            "minimalny_wiek": age,
            "cena": price,
            "waluta": _clean(values.get("waluta")) or "PLN",
            "status_gra": _clean(values.get("status_gra")) or "Nie grane",
            "status_kolekcja": _clean(values.get("status_kolekcja")) or "W kolekcji",
            "wydawca_id": publisher_id,
            "wydawca": publisher_name,
            "rok_wydania": year,
        }
        payload = [normalized[field] for field in fields]
        with self.db.connect("planszowe.db", write=True) as connection:
            if record_id is None:
                record_id = self.db.next_id("planszowe.db", "planszowe")
                placeholders = ", ".join("?" for _ in fields)
                connection.execute(
                    f"INSERT INTO planszowe (id, {', '.join(fields)}) VALUES (?, {placeholders})",
                    (record_id, *payload),
                )
            else:
                assignments = ", ".join(f"{field}=?" for field in fields)
                connection.execute(
                    f"UPDATE planszowe SET {assignments} WHERE id=?",
                    (*payload, record_id),
                )
        return int(record_id)

    def delete_board_game(self, record_id: int) -> None:
        with self.db.connect("planszowe.db", write=True) as connection:
            connection.execute("DELETE FROM planszowe WHERE id=?", (record_id,))

    @staticmethod
    def _calendar_description(session: dict[str, Any]) -> str:
        return session_description(session)

    @staticmethod
    def _ics_escape(value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n")
            .replace("\n", "\\n")
            .replace("\r", "\\n")
        )

    def export_session_ics(self, session: dict[str, Any], destination: Path) -> Path:
        destination = Path(destination)
        if destination.suffix.lower() != ".ics":
            destination = destination.with_suffix(".ics")
        event_date = datetime.strptime(str(session["data_sesji"]), "%Y-%m-%d").date()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Lioheart//Sesyjka GTK4//PL",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:sesyjka-session-{int(session['id'])}@github.com/Lioheart/Sesyjka",
            f"DTSTAMP:{timestamp}",
            f"DTSTART;VALUE=DATE:{event_date.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(event_date + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{self._ics_escape(session_summary(session))}",
            f"DESCRIPTION:{self._ics_escape(self._calendar_description(session))}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        return destination

    def export_sessions_ics(self, destination: Path) -> Path:
        destination = Path(destination)
        if destination.suffix.lower() != ".ics":
            destination = destination.with_suffix(".ics")
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Lioheart//Sesyjka GTK4//PL",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "X-WR-CALNAME:Sesje RPG",
        ]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for session in self.sessions():
            event_date = datetime.strptime(str(session["data_sesji"]), "%Y-%m-%d").date()
            summary = session_summary(session)
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:sesyjka-session-{int(session['id'])}@github.com/Lioheart/Sesyjka",
                    f"DTSTAMP:{timestamp}",
                    f"DTSTART;VALUE=DATE:{event_date.strftime('%Y%m%d')}",
                    f"DTEND;VALUE=DATE:{(event_date + timedelta(days=1)).strftime('%Y%m%d')}",
                    f"SUMMARY:{self._ics_escape(summary)}",
                    f"DESCRIPTION:{self._ics_escape(self._calendar_description(session))}",
                    "TRANSP:TRANSPARENT",
                    "END:VEVENT",
                ]
            )
        lines.append("END:VCALENDAR")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        return destination

    def export_sessions_csv(self, destination: Path) -> Path:
        destination = Path(destination)
        if destination.suffix.lower() != ".csv":
            destination = destination.with_suffix(".csv")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=(
                    "Subject", "Start Date", "Start Time", "End Date", "End Time",
                    "All Day Event", "Description", "Location", "Private",
                ),
            )
            writer.writeheader()
            for session in self.sessions():
                event_date = datetime.strptime(str(session["data_sesji"]), "%Y-%m-%d").date()
                writer.writerow(
                    {
                        "Subject": f"Sesja RPG: {session.get('system_nazwa') or 'Bez systemu'}",
                        "Start Date": event_date.strftime("%m/%d/%Y"),
                        "Start Time": "",
                        "End Date": event_date.strftime("%m/%d/%Y"),
                        "End Time": "",
                        "All Day Event": "True",
                        "Description": self._calendar_description(session),
                        "Location": str(session.get("tryb_gry") or ""),
                        "Private": "False",
                    }
                )
        return destination

    @staticmethod
    def _format_file_size(size: Any) -> str:
        try:
            value = int(size or 0)
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            return ""
        units = ("B", "KB", "MB", "GB", "TB")
        amount = float(value)
        index = 0
        while amount >= 1024 and index < len(units) - 1:
            amount /= 1024
            index += 1
        return f"{amount:.1f} {units[index]}" if index else f"{value} B"

    def storage_roots(self) -> list[dict[str, Any]]:
        if not self.db.has_active_database("zasoby.db"):
            return []
        rows = self.db.table_rows(
            "zasoby.db",
            """
            SELECT id, uuid, nazwa, typ, sciezka_bazowa, aktywny
            FROM magazyny
            ORDER BY nazwa COLLATE NOCASE
            """,
        )
        result = []
        for row in rows:
            item = dict(row)
            base = Path(str(item.get("sciezka_bazowa") or "")).expanduser()
            item["dostepny"] = bool(base.is_dir())
            result.append(item)
        return result

    def unmapped_storage_roots(self) -> list[dict[str, Any]]:
        if not self.db.has_active_database("zasoby.db"):
            return []
        mapped = {str(item["uuid"]) for item in self.storage_roots()}
        rows = self.db.table_rows(
            "zasoby.db",
            """
            SELECT magazyn_uuid, COUNT(*) AS count
            FROM lokalizacje
            WHERE TRIM(COALESCE(magazyn_uuid, '')) <> ''
            GROUP BY magazyn_uuid
            ORDER BY count DESC, magazyn_uuid
            """,
        )
        return [
            {"uuid": str(row["magazyn_uuid"]), "count": int(row["count"])}
            for row in rows
            if str(row["magazyn_uuid"]) not in mapped
        ]

    def save_storage_root(self, values: dict[str, Any], record_id: int | None = None) -> int:
        name = str(values.get("nazwa") or "").strip()
        storage_type = str(values.get("typ") or "Lokalny").strip() or "Lokalny"
        base_path = str(values.get("sciezka_bazowa") or "").strip()
        if not name:
            raise ValueError("Nazwa magazynu jest wymagana.")
        if not base_path:
            raise ValueError("Wybierz katalog magazynu.")
        path = Path(base_path).expanduser()
        if not path.is_dir():
            raise ValueError("Wybrany katalog magazynu nie istnieje.")
        normalized = str(path.resolve())
        with self.db.connect("zasoby.db", write=True) as connection:
            if record_id is None:
                record_id = self.db.next_id("zasoby.db", "magazyny")
                storage_uuid = str(values.get("uuid") or uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO magazyny (id, uuid, nazwa, typ, sciezka_bazowa, aktywny)
                    VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (record_id, storage_uuid, name, storage_type, normalized),
                )
            else:
                connection.execute(
                    """
                    UPDATE magazyny
                    SET nazwa=?, typ=?, sciezka_bazowa=?, aktywny=?
                    WHERE id=?
                    """,
                    (name, storage_type, normalized, int(bool(values.get("aktywny", True))), record_id),
                )
        return int(record_id)

    def delete_storage_root(self, record_id: int) -> None:
        rows = self.db.table_rows(
            "zasoby.db", "SELECT uuid FROM magazyny WHERE id=?", (record_id,)
        )
        if not rows:
            return
        storage_uuid = str(rows[0]["uuid"] or "")
        linked = int(
            self.db.table_rows(
                "zasoby.db",
                "SELECT COUNT(*) AS count FROM lokalizacje WHERE magazyn_uuid=?",
                (storage_uuid,),
            )[0]["count"]
        )
        if linked:
            raise ValueError("Nie można usunąć magazynu używanego przez zapisane lokalizacje.")
        with self.db.connect("zasoby.db", write=True) as connection:
            connection.execute("DELETE FROM magazyny WHERE id=?", (record_id,))

    def resource_locations(self, resource_id: int) -> list[dict[str, Any]]:
        if not self.db.has_active_database("zasoby.db"):
            return []
        storages = {str(item["uuid"]): item for item in self.storage_roots()}
        rows = self.db.table_rows(
            "zasoby.db",
            """
            SELECT id, zasob_id, typ, magazyn_uuid, sciezka_wzgledna, url,
                   provider_ref, preferowana, ostatnio_dostepny
            FROM lokalizacje WHERE zasob_id=?
            ORDER BY preferowana DESC, id
            """,
            (resource_id,),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            storage = storages.get(str(item.get("magazyn_uuid") or ""))
            item["magazyn_nazwa"] = storage.get("nazwa", "") if storage else ""
            item["sciezka_pelna"] = ""
            available = False
            if storage and item.get("sciezka_wzgledna"):
                full_path = Path(str(storage.get("sciezka_bazowa") or "")) / str(item["sciezka_wzgledna"])
                item["sciezka_pelna"] = str(full_path)
                available = full_path.is_file()
            elif item.get("url"):
                available = True
            item["dostepny"] = available
            result.append(item)
        return result

    def _resource_summary(self, resource_id: int) -> tuple[str, str, int]:
        locations = self.resource_locations(resource_id)
        if not locations:
            return "Brak", "", 0
        local = [item for item in locations if item.get("sciezka_wzgledna")]
        online = [item for item in locations if item.get("url")]
        available_local = [item for item in local if item.get("dostepny")]
        if available_local:
            status = "Dostępny lokalnie"
        elif online:
            status = "Online"
        elif local:
            status = "Magazyn niedostępny"
        else:
            status = "Brak"
        labels: list[str] = []
        for item in locations[:3]:
            if item.get("magazyn_nazwa"):
                labels.append(str(item["magazyn_nazwa"]))
            elif item.get("typ"):
                labels.append(str(item["typ"]))
        summary = ", ".join(dict.fromkeys(labels))
        return status, summary, len(locations)

    def digital_resources(self) -> list[dict[str, Any]]:
        if not self.db.has_active_database("zasoby.db"):
            return []
        positions = {int(item["id"]): item for item in self.systems()}
        rows = self.db.table_rows(
            "zasoby.db",
            """
            SELECT id, pozycja_rpg_id, typ, nazwa, dostawca, format, sha256,
                   nazwa_pliku, tytul_pliku, external_id, product_url, rozmiar, isbn,
                   wydawca, data_zakupu, utworzono, zmodyfikowano
            FROM zasoby
            ORDER BY nazwa COLLATE NOCASE, id
            """,
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            position = positions.get(int(item["pozycja_rpg_id"])) if item.get("pozycja_rpg_id") else None
            item["pozycja_nazwa"] = position.get("nazwa", "") if position else ""
            item["system_nazwa"] = position.get("system_gry_nazwa", "") if position else ""
            status, location_summary, location_count = self._resource_summary(int(item["id"]))
            item["dostepnosc"] = status
            item["lokalizacje"] = location_summary
            item["liczba_lokalizacji"] = location_count
            item["plik_tekst"] = str(item.get("tytul_pliku") or item.get("nazwa_pliku") or "")
            item["rozmiar_tekst"] = self._format_file_size(item.get("rozmiar"))
            result.append(item)
        return result

    @staticmethod
    def _vtt_label_from_resource(resource_format: Any, provider: Any) -> str:
        candidates = [str(resource_format or "").strip(), str(provider or "").strip()]
        platform_tokens = ("foundry", "roll20", "fantasy grounds", "vtt")
        for candidate in candidates:
            if candidate and any(token in candidate.casefold() for token in platform_tokens):
                return candidate
        return "VTT"

    def _mark_position_formats_from_resources(
        self,
        resources: list[tuple[int | None, str, Any, Any]],
    ) -> None:
        """Propagate linked digital formats to RPG collection flags.

        This is intentionally additive. Linking a PDF or VTT marks the matching
        format on the RPG position, but unlinking or deleting a resource never
        clears a flag that may have been set manually or may describe another
        copy owned by the user.
        """
        updates: dict[int, dict[str, Any]] = {}
        for raw_position_id, raw_type, resource_format, provider in resources:
            if raw_position_id in (None, ""):
                continue
            position_id = int(raw_position_id)
            resource_type = str(raw_type or "").strip().casefold()
            state = updates.setdefault(position_id, {"pdf": False, "vtt": None})
            if resource_type == "pdf":
                state["pdf"] = True
            elif resource_type == "vtt" and not state["vtt"]:
                state["vtt"] = self._vtt_label_from_resource(resource_format, provider)

        if not updates:
            return
        with self.db.connect("systemy_rpg.db", write=True) as connection:
            for position_id, state in updates.items():
                if state["pdf"]:
                    connection.execute(
                        "UPDATE systemy_rpg SET pdf=1 WHERE id=? AND COALESCE(pdf, 0)=0",
                        (position_id,),
                    )
                if state["vtt"]:
                    connection.execute(
                        """
                        UPDATE systemy_rpg SET vtt=?
                        WHERE id=? AND TRIM(COALESCE(vtt, ''))=''
                        """,
                        (str(state["vtt"]), position_id),
                    )

    def save_digital_resource(self, values: dict[str, Any], record_id: int | None = None) -> int:
        name = str(values.get("nazwa") or "").strip()
        if not name:
            raise ValueError("Nazwa zasobu jest wymagana.")
        resource_type = str(values.get("typ") or "PDF").strip() or "PDF"
        position_id = values.get("pozycja_rpg_id")
        if position_id not in (None, ""):
            valid_ids = {int(item["id"]) for item in self.systems() if str(item.get("typ") or "").casefold() != "grupa"}
            position_id = int(position_id)
            if position_id not in valid_ids:
                raise ValueError("Wybrana pozycja RPG nie istnieje.")
        else:
            position_id = None
        fields = (
            "pozycja_rpg_id", "typ", "nazwa", "dostawca", "format", "sha256",
            "nazwa_pliku", "tytul_pliku", "external_id", "product_url", "rozmiar", "isbn",
            "wydawca", "data_zakupu",
        )
        normalized = dict(values)
        normalized.update({"pozycja_rpg_id": position_id, "typ": resource_type, "nazwa": name})
        payload = [_clean(normalized.get(field)) for field in fields]
        with self.db.connect("zasoby.db", write=True) as connection:
            if record_id is None:
                record_id = self.db.next_id("zasoby.db", "zasoby")
                connection.execute(
                    f"INSERT INTO zasoby (id, {', '.join(fields)}) VALUES (?, {', '.join('?' for _ in fields)})",
                    (record_id, *payload),
                )
            else:
                assignments = ", ".join(f"{field}=?" for field in fields)
                connection.execute(
                    f"UPDATE zasoby SET {assignments}, zmodyfikowano=CURRENT_TIMESTAMP WHERE id=?",
                    (*payload, record_id),
                )
        self._mark_position_formats_from_resources(
            [(position_id, resource_type, normalized.get("format"), normalized.get("dostawca"))]
        )
        return int(record_id)

    def delete_digital_resource(self, record_id: int) -> None:
        with self.db.connect("zasoby.db", write=True) as connection:
            connection.execute("DELETE FROM zasoby WHERE id=?", (record_id,))

    def save_resource_location(self, resource_id: int, values: dict[str, Any], record_id: int | None = None) -> int:
        resource_exists = bool(
            self.db.table_rows("zasoby.db", "SELECT 1 FROM zasoby WHERE id=?", (resource_id,))
        )
        if not resource_exists:
            raise ValueError("Zasób cyfrowy nie istnieje.")
        storage_uuid = str(values.get("magazyn_uuid") or "").strip() or None
        relative_path = str(values.get("sciezka_wzgledna") or "").strip() or None
        url = str(values.get("url") or "").strip() or None
        location_type = str(values.get("typ") or ("Plik" if relative_path else "WWW")).strip()
        if relative_path and not storage_uuid:
            raise ValueError("Lokalny plik musi należeć do magazynu.")
        if storage_uuid:
            valid = {str(item["uuid"]) for item in self.storage_roots()}
            if storage_uuid not in valid:
                raise ValueError("Wybrany magazyn nie istnieje na tym urządzeniu.")
        if not relative_path and not url:
            raise ValueError("Podaj plik albo adres URL.")
        with self.db.connect("zasoby.db", write=True) as connection:
            if values.get("preferowana"):
                connection.execute("UPDATE lokalizacje SET preferowana=0 WHERE zasob_id=?", (resource_id,))
            payload = (
                resource_id, location_type, storage_uuid, relative_path, url,
                _clean(values.get("provider_ref")), int(bool(values.get("preferowana"))),
                int(bool(values.get("ostatnio_dostepny"))),
            )
            if record_id is None:
                record_id = self.db.next_id("zasoby.db", "lokalizacje")
                connection.execute(
                    """
                    INSERT INTO lokalizacje
                    (id, zasob_id, typ, magazyn_uuid, sciezka_wzgledna, url,
                     provider_ref, preferowana, ostatnio_dostepny)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (record_id, *payload),
                )
            else:
                connection.execute(
                    """
                    UPDATE lokalizacje SET typ=?, magazyn_uuid=?, sciezka_wzgledna=?,
                    url=?, provider_ref=?, preferowana=?, ostatnio_dostepny=?
                    WHERE id=? AND zasob_id=?
                    """,
                    (*payload[1:], record_id, resource_id),
                )
        return int(record_id)

    def delete_resource_location(self, record_id: int) -> None:
        with self.db.connect("zasoby.db", write=True) as connection:
            connection.execute("DELETE FROM lokalizacje WHERE id=?", (record_id,))

    def best_resource_target(self, resource_id: int) -> dict[str, Any] | None:
        locations = self.resource_locations(resource_id)
        preferred = sorted(locations, key=lambda item: (not bool(item.get("preferowana")), int(item.get("id") or 0)))
        for item in preferred:
            if item.get("sciezka_pelna") and item.get("dostepny"):
                return {"kind": "file", "value": item["sciezka_pelna"], "location": item}
        for item in preferred:
            if item.get("url"):
                return {"kind": "url", "value": item["url"], "location": item}
        rows = self.db.table_rows(
            "zasoby.db", "SELECT product_url FROM zasoby WHERE id=?", (resource_id,)
        )
        if rows and rows[0]["product_url"]:
            return {"kind": "url", "value": str(rows[0]["product_url"]), "location": None}
        return None

    def import_scanned_pdfs(self, storage_id: int, scan_results: list[Any]) -> dict[str, int]:
        storages = {int(item["id"]): item for item in self.storage_roots()}
        storage = storages.get(int(storage_id))
        if not storage:
            raise ValueError("Wybrany magazyn nie istnieje.")
        storage_uuid = str(storage["uuid"])
        created = linked = existing = 0
        linked_positions: set[int] = set()
        with self.db.connect("zasoby.db", write=True) as connection:
            for scanned in scan_results:
                duplicate = connection.execute(
                    "SELECT id, pozycja_rpg_id FROM zasoby WHERE sha256=? AND sha256<>'' LIMIT 1",
                    (str(scanned.sha256),),
                ).fetchone()
                if duplicate:
                    resource_id = int(duplicate["id"])
                    existing += 1
                    if duplicate["pozycja_rpg_id"] is None and scanned.suggested_rpg_id is not None:
                        connection.execute(
                            "UPDATE zasoby SET pozycja_rpg_id=?, zmodyfikowano=CURRENT_TIMESTAMP WHERE id=?",
                            (int(scanned.suggested_rpg_id), resource_id),
                        )
                        linked_positions.add(int(scanned.suggested_rpg_id))
                        linked += 1
                    elif duplicate["pozycja_rpg_id"] is not None:
                        linked_positions.add(int(duplicate["pozycja_rpg_id"]))
                else:
                    resource_id = int(connection.execute("SELECT COALESCE(MAX(id),0)+1 FROM zasoby").fetchone()[0])
                    connection.execute(
                        """
                        INSERT INTO zasoby
                        (id, pozycja_rpg_id, typ, nazwa, dostawca, format, sha256,
                         nazwa_pliku, rozmiar)
                        VALUES (?, ?, 'PDF', ?, 'Plik lokalny', 'PDF', ?, ?, ?)
                        """,
                        (
                            resource_id,
                            scanned.suggested_rpg_id,
                            Path(scanned.filename).stem,
                            scanned.sha256,
                            scanned.filename,
                            int(scanned.size),
                        ),
                    )
                    created += 1
                    if scanned.suggested_rpg_id is not None:
                        linked_positions.add(int(scanned.suggested_rpg_id))
                        linked += 1
                exists_location = connection.execute(
                    """
                    SELECT 1 FROM lokalizacje
                    WHERE zasob_id=? AND magazyn_uuid=? AND sciezka_wzgledna=?
                    """,
                    (resource_id, storage_uuid, scanned.relative_path),
                ).fetchone()
                if not exists_location:
                    location_id = int(connection.execute("SELECT COALESCE(MAX(id),0)+1 FROM lokalizacje").fetchone()[0])
                    connection.execute(
                        """
                        INSERT INTO lokalizacje
                        (id, zasob_id, typ, magazyn_uuid, sciezka_wzgledna,
                         preferowana, ostatnio_dostepny)
                        VALUES (?, ?, 'Plik', ?, ?, 0, 1)
                        """,
                        (location_id, resource_id, storage_uuid, scanned.relative_path),
                    )
        self._mark_position_formats_from_resources(
            [(position_id, "PDF", "PDF", "Plik lokalny") for position_id in sorted(linked_positions)]
        )
        return {"created": created, "linked": linked, "existing": existing, "found": len(scan_results)}

    def import_drivethru_library(self, items: list[Any]) -> dict[str, int]:
        systems = self.systems()
        by_isbn = {
            re.sub(r"[^0-9Xx]", "", str(item.get("isbn") or "")).upper(): int(item["id"])
            for item in systems
            if item.get("isbn") and str(item.get("typ") or "").casefold() != "grupa"
        }
        from .digital_resources import match_rpg_item

        created = updated = linked = 0
        linked_formats: list[tuple[int | None, str, Any, Any]] = []
        with self.db.connect("zasoby.db", write=True) as connection:
            for entry in items:
                isbn = re.sub(r"[^0-9Xx]", "", str(entry.isbn or "")).upper()
                position_id = by_isbn.get(isbn) if isbn else None
                if position_id is None:
                    match_source = entry.product_title or entry.title or entry.filename
                    position_id, _confidence = match_rpg_item(match_source, systems)
                    if position_id is None and entry.product_title and entry.title != entry.product_title:
                        position_id, _confidence = match_rpg_item(entry.title or entry.filename, systems)
                existing = connection.execute(
                    "SELECT id, pozycja_rpg_id FROM zasoby WHERE external_id=?",
                    (entry.external_id,),
                ).fetchone()
                values = (
                    position_id,
                    entry.resource_type,
                    entry.title or entry.filename,
                    "DriveThruRPG",
                    entry.format_name,
                    entry.sha256 or None,
                    entry.filename or None,
                    entry.file_title or None,
                    entry.product_url,
                    entry.size,
                    entry.isbn or None,
                    entry.publisher or None,
                    entry.date_purchased or None,
                )
                if existing:
                    resource_id = int(existing["id"])
                    if existing["pozycja_rpg_id"] is not None and position_id is None:
                        position_id = int(existing["pozycja_rpg_id"])
                        values = (position_id, *values[1:])
                    connection.execute(
                        """
                        UPDATE zasoby SET pozycja_rpg_id=?, typ=?, nazwa=?, dostawca=?,
                        format=?, sha256=?, nazwa_pliku=?, tytul_pliku=?, product_url=?, rozmiar=?,
                        isbn=?, wydawca=?, data_zakupu=?, zmodyfikowano=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                        (*values, resource_id),
                    )
                    updated += 1
                else:
                    resource_id = int(connection.execute("SELECT COALESCE(MAX(id),0)+1 FROM zasoby").fetchone()[0])
                    connection.execute(
                        """
                        INSERT INTO zasoby
                        (id, pozycja_rpg_id, typ, nazwa, dostawca, format, sha256,
                         nazwa_pliku, tytul_pliku, external_id, product_url, rozmiar, isbn,
                         wydawca, data_zakupu)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (resource_id, *values[:8], entry.external_id, *values[8:]),
                    )
                    created += 1
                if position_id is not None:
                    linked += 1
                    linked_formats.append(
                        (position_id, entry.resource_type, entry.format_name, "DriveThruRPG")
                    )
                provider_ref = f"{entry.order_product_id}:{entry.file_index if entry.file_index is not None else 'product'}"
                location = connection.execute(
                    "SELECT id FROM lokalizacje WHERE zasob_id=? AND typ='DriveThruRPG'",
                    (resource_id,),
                ).fetchone()
                if location:
                    connection.execute(
                        "UPDATE lokalizacje SET url=?, provider_ref=? WHERE id=?",
                        (entry.product_url, provider_ref, int(location["id"])),
                    )
                else:
                    location_id = int(connection.execute("SELECT COALESCE(MAX(id),0)+1 FROM lokalizacje").fetchone()[0])
                    connection.execute(
                        """
                        INSERT INTO lokalizacje
                        (id, zasob_id, typ, url, provider_ref, preferowana, ostatnio_dostepny)
                        VALUES (?, ?, 'DriveThruRPG', ?, ?, 0, 1)
                        """,
                        (location_id, resource_id, entry.product_url, provider_ref),
                    )
        self._mark_position_formats_from_resources(linked_formats)
        return {"created": created, "updated": updated, "linked": linked, "found": len(items)}

    def statistics(self) -> dict[str, Any]:
        systems = self.systems()
        sessions = self.sessions()
        players = self.players()
        publishers = self.publishers()
        board_games = self.board_games()
        digital_resources = self.digital_resources()

        sessions_by_system = Counter(
            str(item.get("system_nazwa") or "Bez systemu") for item in sessions
        )
        positions_by_system = Counter(
            str(item.get("system_gry_nazwa") or "Bez systemu") for item in systems
        )
        physical = [item for item in systems if item.get("fizyczny")]
        pdf = [item for item in systems if item.get("pdf")]
        physical_by_system = Counter(
            str(item.get("system_gry_nazwa") or "Bez systemu") for item in physical
        )
        pdf_by_system = Counter(
            str(item.get("system_gry_nazwa") or "Bez systemu") for item in pdf
        )

        player_appearances_by_id: Counter[int] = Counter()
        for session in sessions:
            player_appearances_by_id.update(
                int(player_id) for player_id in session["player_ids"]
            )
        player_appearances = sorted(
            (
                (str(player["nick"]), player_appearances_by_id.get(int(player["id"]), 0))
                for player in players
            ),
            key=lambda item: (-item[1], item[0].casefold()),
        )

        publisher_position_counts: Counter[int] = Counter(
            int(item["wydawca_id"])
            for item in systems
            if item.get("wydawca_id") is not None
        )
        publisher_chart = sorted(
            (
                (
                    str(publisher["nazwa"]),
                    publisher_position_counts.get(int(publisher["id"]), 0),
                )
                for publisher in publishers
            ),
            key=lambda item: (-item[1], item[0].casefold()),
        )

        sessions_by_year: Counter[str] = Counter()
        for session in sessions:
            date_text = str(session.get("data_sesji") or "").strip()
            year = ""
            if len(date_text) >= 4 and date_text[:4].isdigit():
                year = date_text[:4]
            elif "." in date_text:
                parts = date_text.split(".")
                if len(parts) == 3 and parts[2].isdigit():
                    year = parts[2]
            if year:
                sessions_by_year[year] += 1

        def sorted_counter(counter: Counter[str]) -> list[tuple[str, int]]:
            return sorted(
                counter.items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )

        board_game_types = Counter(
            "Karcianki" if str(item.get("typ") or "").casefold() == "gra karciana" else "Planszówki"
            for item in board_games
        )

        value_by_currency: dict[str, Decimal] = {}

        def add_value(value: Any, currency: Any) -> None:
            if value in (None, ""):
                return
            try:
                parsed = Decimal(str(value).strip().replace(",", "."))
            except (InvalidOperation, ValueError):
                return
            if parsed <= 0:
                return
            code = str(currency or "PLN").strip().upper() or "PLN"
            value_by_currency[code] = value_by_currency.get(code, Decimal("0")) + parsed

        for item in systems:
            add_value(item.get("cena_zakupu"), item.get("waluta_zakupu"))
        for item in board_games:
            add_value(item.get("cena"), item.get("waluta"))

        def format_currency(value: Decimal, currency: str) -> str:
            amount = f"{value:,.2f}".replace(",", " ").replace(".", ",")
            return f"{amount} {currency}"

        collection_value = " · ".join(
            format_currency(value, currency)
            for currency, value in sorted(value_by_currency.items())
        ) or "0,00 PLN"

        counts = {
            "Pozycje RPG": len(systems),
            "Sesje": len(sessions),
            "Gracze": len(players),
            "Wydawcy": len(publishers),
            "Fizyczne": len(physical),
            "PDF": len(pdf),
            "Planszówki/Karcianki": len(board_games),
            "Zasoby cyfrowe": len(digital_resources),
            "Wartość pozycji": collection_value,
        }

        charts = {
            "Pozycje RPG": {
                "title": "Pozycje RPG według systemu",
                "items": sorted_counter(positions_by_system),
            },
            "Sesje": {
                "title": "Liczba sesji RPG według roku",
                "items": sorted(
                    sessions_by_year.items(),
                    key=lambda item: item[0],
                    reverse=True,
                ),
            },
            "Gracze": {
                "title": "Udział graczy w sesjach",
                "items": player_appearances,
            },
            "Wydawcy": {
                "title": "Pozycje RPG według wydawcy",
                "items": publisher_chart,
            },
            "Fizyczne": {
                "title": "Fizyczne pozycje RPG według systemu",
                "items": sorted_counter(physical_by_system),
            },
            "PDF": {
                "title": "Pozycje PDF według systemu",
                "items": sorted_counter(pdf_by_system),
            },
            "Planszówki/Karcianki": {
                "title": "Gry planszowe i karciane",
                "items": [("Planszówki", board_game_types.get("Planszówki", 0)), ("Karcianki", board_game_types.get("Karcianki", 0))],
            },
            "Zasoby cyfrowe": {
                "title": "Zasoby cyfrowe według typu",
                "items": sorted_counter(Counter(str(item.get("typ") or "Inne") for item in digital_resources)),
            },
        }
        return {
            "counts": counts,
            "systems": sorted_counter(sessions_by_system),
            "players": player_appearances,
            "charts": charts,
        }
