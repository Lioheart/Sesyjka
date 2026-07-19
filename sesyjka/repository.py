from __future__ import annotations

from collections import Counter
from datetime import datetime
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
        for key in ("cena_zakupu", "cena_sprzedazy", "cena_fiz", "cena_pdf", "cena_vtt"):
            value = normalized.get(key)
            if value in (None, ""):
                normalized[key] = None
            else:
                normalized[key] = float(str(value).replace(",", "."))
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

    def statistics(self) -> dict[str, Any]:
        systems = self.systems()
        sessions = self.sessions()
        players = self.players()
        publishers = self.publishers()

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

        counts = {
            "Pozycje RPG": len(systems),
            "Sesje": len(sessions),
            "Gracze": len(players),
            "Wydawcy": len(publishers),
            "Fizyczne": len(physical),
            "PDF": len(pdf),
        }

        def sorted_counter(counter: Counter[str]) -> list[tuple[str, int]]:
            return sorted(
                counter.items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )

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
        }
        return {
            "counts": counts,
            "systems": sorted_counter(sessions_by_system),
            "players": player_appearances,
            "charts": charts,
        }
