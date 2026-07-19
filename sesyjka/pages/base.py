from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..dialogs import confirm, info
from ..repository import Repository
from ..widgets import DataTable


class CrudPage(Gtk.Box):
    def __init__(
        self,
        parent_window: Gtk.Window,
        repository: Repository,
        columns: Sequence[tuple[str, str]],
        entity_label: str,
        *,
        grouped: bool = False,
        tree_key: str = "nazwa",
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.parent_window = parent_window
        self.add_css_class("content-page")
        self.repository = repository
        self.entity_label = entity_label
        self._all_records: list[dict[str, Any]] = []
        self.on_data_changed: Callable[[], None] | None = None
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Filtruj całą tabelę")
        self.search.set_hexpand(True)
        self.search.connect("search-changed", lambda _entry: self.apply_filter())
        toolbar.append(self.search)

        self.add_button = Gtk.Button(label="Dodaj")
        self.add_button.add_css_class("suggested-action")
        self.add_button.connect("clicked", lambda _button: self.open_editor(None))
        toolbar.append(self.add_button)

        self.edit_button = Gtk.Button(label="Edytuj")
        self.edit_button.connect("clicked", lambda _button: self.edit_selected())
        toolbar.append(self.edit_button)

        self.delete_button = Gtk.Button(label="Usuń")
        self.delete_button.add_css_class("destructive-action")
        self.delete_button.connect("clicked", lambda _button: self.delete_selected())
        toolbar.append(self.delete_button)

        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh.set_tooltip_text("Odśwież")
        refresh.connect("clicked", lambda _button: self.refresh())
        toolbar.append(refresh)
        self.append(toolbar)

        self.table = DataTable(columns, grouped=grouped, tree_key=tree_key)
        self.table.connect_activate(self.open_editor)
        self.table.set_context_actions(self.open_editor, self.request_delete)
        self.table.set_view_changed_callback(self.update_status)
        self.append(self.table)
        self.status = Gtk.Label(xalign=0.0)
        self.status.add_css_class("dim-label")
        self.append(self.status)

    def set_read_only(self, value: bool) -> None:
        for button in (self.add_button, self.edit_button, self.delete_button):
            button.set_sensitive(not value)
        self.table.set_read_only(value)

    def load_records(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def open_editor(self, record: dict[str, Any] | None) -> None:
        raise NotImplementedError

    def delete_record(self, record_id: int) -> None:
        raise NotImplementedError

    def refresh(self) -> None:
        try:
            self._all_records = self.load_records()
            self.table.set_records(self._all_records)
            self.apply_filter()
        except Exception as exc:
            info(self.parent_window, "Błąd odczytu", str(exc), error=True)

    def apply_filter(self) -> None:
        self.table.set_global_filter(self.search.get_text())
        self.update_status()

    def update_status(self) -> None:
        self.status.set_text(
            f"Rekordy: {self.table.visible_count()} z {self.table.total_count()}"
        )

    def _validated_selected_record(self) -> dict[str, Any] | None:
        record = self.table.selected_record()
        if record is None:
            info(self.parent_window, "Brak zaznaczenia", "Zaznacz rekord.")
            return None
        if record.get("_is_group") and not record.get("_is_entity"):
            info(
                self.parent_window,
                "Wybrano grupę",
                "Wybierz konkretną pozycję wewnątrz systemu.",
            )
            return None
        return record

    def edit_selected(self) -> None:
        record = self._validated_selected_record()
        if record is not None:
            self.open_editor(record)

    def delete_selected(self) -> None:
        record = self._validated_selected_record()
        if record is not None:
            self.request_delete(record)

    def request_delete(self, record: dict[str, Any]) -> None:
        if record.get("_is_group") and not record.get("_is_entity"):
            return
        label = self.describe_record(record)
        confirm(
            self.parent_window,
            f"Usuń {self.entity_label}",
            f"Czy usunąć: {label}?",
            lambda: self._delete_confirmed(int(record["id"])),
        )

    def _delete_confirmed(self, record_id: int) -> None:
        try:
            self.delete_record(record_id)
            self.refresh()
            self.notify_data_changed()
        except Exception as exc:
            info(self.parent_window, "Błąd usuwania", str(exc), error=True)

    def notify_data_changed(self) -> None:
        if self.on_data_changed is not None:
            self.on_data_changed()

    def describe_record(self, record: dict[str, Any]) -> str:
        return str(record.get("nazwa") or record.get("nick") or record.get("id"))
