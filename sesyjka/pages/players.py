from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..dialogs import ModalWindow, info, make_entry
from ..repository import Repository
from ..widgets import FormGrid, TextDropDown
from .base import CrudPage


class PlayersPage(CrudPage):
    def __init__(self, parent_window: Gtk.Window, repository: Repository) -> None:
        super().__init__(
            parent_window,
            repository,
            (
                ("ID", "id"),
                ("Nick", "nick"),
                ("Imię i nazwisko", "imie_nazwisko"),
                ("Płeć", "plec"),
                ("Grupa", "grupa"),
                ("Social media", "social"),
                ("Główny", "glowny_tekst"),
                ("Ważny", "wazna_tekst"),
            ),
            "gracza",
        )

    def load_records(self) -> list[dict[str, Any]]:
        records = self.repository.players()
        for record in records:
            record["glowny_tekst"] = "Tak" if record.get("glowny_uzytkownik") else ""
            record["wazna_tekst"] = "Tak" if record.get("wazna") else ""
        return records

    def delete_record(self, record_id: int) -> None:
        self.repository.delete_player(record_id)

    def describe_record(self, record: dict[str, Any]) -> str:
        return str(record.get("nick", record["id"]))

    def open_editor(self, record: dict[str, Any] | None) -> None:
        dialog = ModalWindow(
            self.parent_window,
            "Edytuj gracza" if record else "Dodaj gracza",
            width=560,
            height=500,
        )
        form = FormGrid()
        nick = make_entry(record.get("nick") if record else "", "Nick")
        full_name = make_entry(record.get("imie_nazwisko") if record else "", "Imię i nazwisko")
        gender = TextDropDown(
            ["", "Kobieta", "Mężczyzna", "Inna", "Nie podano"],
            str(record.get("plec") or "") if record else "",
        )
        social = make_entry(record.get("social") if record else "", "Profil lub adres")
        group = make_entry(record.get("grupa") if record else "", "Grupa")
        main_user = Gtk.CheckButton(label="Główny użytkownik")
        main_user.set_active(bool(record and record.get("glowny_uzytkownik")))
        important = Gtk.CheckButton(label="Ważny gracz")
        important.set_active(bool(record and record.get("wazna")))
        form.add_row("Nick *", nick)
        form.add_row("Imię i nazwisko", full_name)
        form.add_row("Płeć", gender)
        form.add_row("Social media", social)
        form.add_row("Grupa", group)
        form.add_full(main_user)
        form.add_full(important)
        dialog.add_scrolled_content(form)

        def save() -> None:
            try:
                self.repository.save_player(
                    {
                        "nick": nick.get_text(),
                        "imie_nazwisko": full_name.get_text(),
                        "plec": gender.text(),
                        "social": social.get_text(),
                        "grupa": group.get_text(),
                        "glowny_uzytkownik": main_user.get_active(),
                        "wazna": important.get_active(),
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
