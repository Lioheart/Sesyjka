from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..dialogs import ModalWindow, info, make_entry
from ..repository import Repository
from ..widgets import FormGrid, TextDropDown
from .base import CrudPage


class BoardGamesPage(CrudPage):
    def __init__(self, parent_window: Gtk.Window, repository: Repository) -> None:
        super().__init__(
            parent_window,
            repository,
            (
                ("ID", "id"),
                ("Nazwa", "nazwa"),
                ("Typ", "typ"),
                ("Gracze", "liczba_graczy_tekst"),
                ("Czas", "czas_tekst"),
                ("Wiek", "minimalny_wiek"),
                ("Cena", "cena_tekst"),
                ("Status gry", "status_gra"),
                ("Kolekcja", "status_kolekcja"),
                ("Wydawca", "wydawca"),
                ("Rok", "rok_wydania"),
            ),
            "grę planszową lub karcianą",
        )

    def load_records(self) -> list[dict[str, Any]]:
        return self.repository.board_games()

    def delete_record(self, record_id: int) -> None:
        self.repository.delete_board_game(record_id)

    def open_editor(self, record: dict[str, Any] | None) -> None:
        dialog = ModalWindow(
            self.parent_window,
            "Edytuj grę" if record else "Dodaj grę planszową lub karcianą",
            width=660,
            height=720,
        )
        form = FormGrid()
        name = make_entry(record.get("nazwa") if record else "", "Nazwa gry")
        game_type = TextDropDown(
            ["Gra planszowa", "Gra karciana"],
            str(record.get("typ") or "Gra planszowa") if record else "Gra planszowa",
        )
        min_players = make_entry(record.get("min_graczy") if record else "1", "np. 1")
        max_players = make_entry(record.get("max_graczy") if record else "4", "np. 4")
        time_min = make_entry(record.get("czas_min") if record else "", "minuty")
        time_max = make_entry(record.get("czas_max") if record else "", "minuty")
        minimum_age = make_entry(record.get("minimalny_wiek") if record else "", "np. 10")
        price = make_entry(record.get("cena") if record else "", "Cena")
        currency = make_entry(record.get("waluta") if record else "PLN", "Waluta")
        game_status = TextDropDown(
            ["Nie grane", "Grane", "Ukończone", "Planowane"],
            str(record.get("status_gra") or "Nie grane") if record else "Nie grane",
        )
        collection_status = TextDropDown(
            ["W kolekcji", "Na sprzedaż", "Sprzedane", "Nieposiadane", "Do kupienia", "Pożyczone"],
            str(record.get("status_kolekcja") or "W kolekcji") if record else "W kolekcji",
        )
        publisher = make_entry(record.get("wydawca") if record else "", "Wydawca")
        year = make_entry(record.get("rok_wydania") if record else "", "RRRR")
        notes = Gtk.TextView()
        notes.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        notes.set_size_request(-1, 120)
        if record and record.get("notatki"):
            notes.get_buffer().set_text(str(record["notatki"]))

        form.add_row("Nazwa *", name)
        form.add_row("Typ *", game_type)
        form.add_row("Minimalna liczba graczy *", min_players)
        form.add_row("Maksymalna liczba graczy *", max_players)
        form.add_row("Minimalny czas rozgrywki", time_min)
        form.add_row("Maksymalny czas rozgrywki", time_max)
        form.add_row("Minimalny wiek", minimum_age)
        form.add_row("Cena", price)
        form.add_row("Waluta", currency)
        form.add_row("Status gry", game_status)
        form.add_row("Status kolekcji", collection_status)
        form.add_row("Wydawca", publisher)
        form.add_row("Rok wydania", year)
        notes_frame = Gtk.Frame(label="Notatki")
        notes_frame.set_child(notes)
        form.add_full(notes_frame)
        dialog.add_scrolled_content(form)

        def save() -> None:
            buffer = notes.get_buffer()
            note = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
            try:
                self.repository.save_board_game(
                    {
                        "nazwa": name.get_text(),
                        "typ": game_type.text(),
                        "min_graczy": min_players.get_text(),
                        "max_graczy": max_players.get_text(),
                        "czas_min": time_min.get_text(),
                        "czas_max": time_max.get_text(),
                        "minimalny_wiek": minimum_age.get_text(),
                        "cena": price.get_text(),
                        "waluta": currency.get_text(),
                        "status_gra": game_status.text(),
                        "status_kolekcja": collection_status.text(),
                        "wydawca": publisher.get_text(),
                        "rok_wydania": year.get_text(),
                        "notatki": note,
                    },
                    int(record["id"]) if record else None,
                )
                dialog.close()
                self.refresh()
                self.notify_data_changed()
            except Exception as exc:
                info(dialog, "Błąd zapisu", str(exc), error=True)

        dialog.add_buttons(save)
        dialog.present()
