from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from pathlib import Path
from typing import Any

from .database_manager import DatabaseManager


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class Repository:
    def __init__(self, databases: DatabaseManager) -> None:
        self.db = databases

    def publishers(self) -> list[dict[str, Any]]:
        rows = self.db.table_rows(
            "wydawcy.db",
            "SELECT id, nazwa, strona, kraj FROM wydawcy ORDER BY nazwa COLLATE NOCASE",
        )
        return [dict(row) for row in rows]

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
        if linked_positions or linked_systems:
            raise ValueError(
                "Nie można usunąć wydawcy używanego przez systemy lub pozycje RPG."
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
        publisher_id = values.get("wydawca_id")
        if publisher_id is not None:
            valid_publishers = {int(item["id"]) for item in self.publishers()}
            if int(publisher_id) not in valid_publishers:
                raise ValueError("Wybrany wydawca nie istnieje w bazie wydawców.")
        payload = (
            name,
            int(publisher_id) if publisher_id is not None else None,
            _clean(values.get("jezyk")),
            _clean(values.get("notatki")),
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
        normalized = dict(values)
        normalized["nazwa"] = name
        normalized["typ"] = item_type
        if item_type.casefold() == "suplement":
            supplement_values = [
                part.strip()
                for part in re.split(r"[;,|\n]+", str(normalized.get("typ_suplementu") or ""))
                if part.strip()
            ]
            normalized["typ_suplementu"] = "; ".join(dict.fromkeys(supplement_values))
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

        parent_id = normalized.get("system_glowny_id")
        if parent_id is not None:
            parent_id = int(parent_id)
            if record_id is not None and parent_id == int(record_id):
                raise ValueError("Pozycja nie może być własnym podręcznikiem nadrzędnym.")
            parent_rows = self.db.table_rows(
                "systemy_rpg.db",
                "SELECT id, system_glowny_id, system_gry_id FROM systemy_rpg WHERE id=?",
                (parent_id,),
            )
            if not parent_rows:
                raise ValueError("Wybrany podręcznik nadrzędny nie istnieje.")
            parent = parent_rows[0]
            if parent["system_gry_id"] is None or int(parent["system_gry_id"]) != int(game_system_id):
                raise ValueError("Podręcznik nadrzędny musi należeć do tego samego systemu RPG.")
            if record_id is not None:
                seen = {parent_id}
                ancestor_id = parent["system_glowny_id"]
                while ancestor_id is not None:
                    ancestor_id = int(ancestor_id)
                    if ancestor_id == int(record_id):
                        raise ValueError("Relacja nadrzędna utworzyłaby cykl w hierarchii.")
                    if ancestor_id in seen:
                        break
                    seen.add(ancestor_id)
                    rows = self.db.table_rows(
                        "systemy_rpg.db",
                        "SELECT system_glowny_id FROM systemy_rpg WHERE id=?",
                        (ancestor_id,),
                    )
                    ancestor_id = rows[0]["system_glowny_id"] if rows else None
            normalized["system_glowny_id"] = parent_id
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
        child_count = int(
            self.db.table_rows(
                "systemy_rpg.db",
                "SELECT COUNT(*) AS count FROM systemy_rpg WHERE system_glowny_id=?",
                (record_id,),
            )[0]["count"]
        )
        if child_count:
            raise ValueError(
                "Nie można usunąć podręcznika, do którego przypisano pozycje podrzędne."
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
        rows = self.db.table_rows(
            "planszowe.db",
            """
            SELECT id, nazwa, typ, min_graczy, max_graczy, czas_min, czas_max,
                   minimalny_wiek, cena, waluta, status_gra, status_kolekcja,
                   wydawca, rok_wydania, notatki
            FROM planszowe ORDER BY nazwa COLLATE NOCASE
            """,
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
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

        fields = (
            "nazwa", "typ", "min_graczy", "max_graczy", "czas_min", "czas_max",
            "minimalny_wiek", "cena", "waluta", "status_gra", "status_kolekcja",
            "wydawca", "rok_wydania", "notatki",
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
            "wydawca": _clean(values.get("wydawca")),
            "rok_wydania": year,
            "notatki": _clean(values.get("notatki")),
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
            summary = f"Sesja RPG: {session.get('system_nazwa') or 'Bez systemu'}"
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

    def statistics(self) -> dict[str, Any]:
        systems = self.systems()
        sessions = self.sessions()
        players = self.players()
        publishers = self.publishers()
        board_games = self.board_games()

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
        }
        return {
            "counts": counts,
            "systems": sorted_counter(sessions_by_system),
            "players": player_appearances,
            "charts": charts,
        }
