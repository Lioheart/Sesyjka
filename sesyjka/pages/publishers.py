from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..dialogs import ModalWindow, info, make_entry
from ..repository import Repository
from ..widgets import FormGrid
from .base import CrudPage


class PublishersPage(CrudPage):
    def __init__(self, parent_window: Gtk.Window, repository: Repository) -> None:
        super().__init__(
            parent_window,
            repository,
            (("ID", "id"), ("Nazwa", "nazwa"), ("Kraj", "kraj"), ("Strona", "strona")),
            "wydawcę",
        )

    def load_records(self) -> list[dict[str, Any]]:
        return self.repository.publishers()

    def delete_record(self, record_id: int) -> None:
        self.repository.delete_publisher(record_id)

    def open_editor(self, record: dict[str, Any] | None) -> None:
        dialog = ModalWindow(
            self.parent_window,
            "Edytuj wydawcę" if record else "Dodaj wydawcę",
            width=520,
            height=300,
        )
        form = FormGrid()
        name = make_entry(record.get("nazwa") if record else "", "Nazwa wydawcy")
        country = make_entry(record.get("kraj") if record else "", "Kraj")
        website = make_entry(record.get("strona") if record else "", "https://")
        form.add_row("Nazwa *", name)
        form.add_row("Kraj", country)
        form.add_row("Strona WWW", website)
        dialog.root_box.append(form)

        def save() -> None:
            try:
                self.repository.save_publisher(
                    {"nazwa": name.get_text(), "kraj": country.get_text(), "strona": website.get_text()},
                    int(record["id"]) if record else None,
                )
                dialog.close()
                self.refresh()
                self.notify_data_changed()
            except Exception as exc:
                info(dialog, "Błąd zapisu", str(exc), error=True)

        dialog.add_buttons(save)
        dialog.present()
