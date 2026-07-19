from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..dialogs import ModalWindow, info, make_entry
from ..repository import Repository
from ..widgets import Choice, ChoiceDropDown, FormGrid, TextDropDown
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

    def _publisher_choices(self) -> list[Choice]:
        return [
            Choice(None, "Brak"),
            *[
                Choice(int(row["id"]), str(row["nazwa"]))
                for row in self.repository.publishers()
            ],
        ]

    def _publisher_selector(
        self,
        dialog_parent: Gtk.Window,
        selected_id: int | None = None,
    ) -> tuple[Gtk.Box, ChoiceDropDown]:
        selector = ChoiceDropDown(self._publisher_choices(), selected_id)
        add_publisher = Gtk.Button(label="Dodaj wydawcę")
        add_publisher.set_tooltip_text("Dodaj wydawcę bez zamykania formularza")

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        selector.set_hexpand(True)
        row.append(selector)
        row.append(add_publisher)

        def refresh_after_add(publisher_id: int) -> None:
            selector.set_choices(self._publisher_choices(), publisher_id)
            self.notify_data_changed()

        add_publisher.connect(
            "clicked",
            lambda _button: self._open_quick_publisher_editor(
                dialog_parent,
                refresh_after_add,
            ),
        )
        return row, selector

    def _open_quick_publisher_editor(
        self,
        parent: Gtk.Window,
        on_saved: Callable[[int], None],
    ) -> None:
        dialog = ModalWindow(parent, "Dodaj wydawcę", width=520, height=360)
        form = FormGrid()
        name = make_entry(placeholder="Nazwa wydawcy")
        country = make_entry(placeholder="Kraj")
        website = make_entry(placeholder="https://...")
        form.add_row("Nazwa *", name)
        form.add_row("Kraj", country)
        form.add_row("Strona WWW", website)
        dialog.add_scrolled_content(form)

        def save() -> None:
            try:
                publisher_id = self.repository.save_publisher(
                    {
                        "nazwa": name.get_text(),
                        "kraj": country.get_text(),
                        "strona": website.get_text(),
                    }
                )
                dialog.close()
                on_saved(publisher_id)
            except Exception as exc:
                info(dialog, "Błąd zapisu", str(exc), error=True)

        dialog.add_buttons(save)
        dialog.present()

    def open_editor(self, record: dict[str, Any] | None) -> None:
        dialog = ModalWindow(
            self.parent_window,
            "Edytuj grę" if record else "Dodaj grę planszową lub karcianą",
            width=660,
            height=680,
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
        publisher_row, publisher = self._publisher_selector(
            dialog,
            int(record["wydawca_id"]) if record and record.get("wydawca_id") is not None else None,
        )
        year = make_entry(record.get("rok_wydania") if record else "", "RRRR")

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
        form.add_row("Wydawca", publisher_row)
        form.add_row("Rok wydania", year)
        dialog.add_scrolled_content(form)

        def save() -> None:
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
                        "wydawca_id": publisher.identifier(),
                        "rok_wydania": year.get_text(),
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
