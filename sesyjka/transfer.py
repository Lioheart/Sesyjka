from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from .database_manager import DatabaseManager
from .dialogs import ModalWindow, confirm, info


class TransferWindow(ModalWindow):
    def __init__(
        self,
        parent: Gtk.Window,
        databases: DatabaseManager,
        on_database_change: Callable[[], None],
        on_guest_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, "Bazy danych", width=620, height=560)
        self.databases = databases
        self.on_database_change = on_database_change
        self.on_guest_change = on_guest_change
        self._choosers: list[Gtk.FileChooserNative] = []

        intro = Gtk.Label(
            label=(
                "Eksport tworzy kopię czterech baz SQLite. Import zastępuje własne bazy po utworzeniu "
                "kopii zapasowej. Tryb gościa otwiera wskazany zestaw wyłącznie do odczytu."
            ),
            wrap=True,
            xalign=0.0,
        )
        self.root_box.append(intro)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_hexpand(True)
        actions = [
            ("Eksport ZIP", "Zapisz komplet baz w archiwum ZIP.", self.choose_export_zip),
            ("Eksport folderu", "Zapisz cztery pliki SQLite jako osobne pliki.", self.choose_export_folder),
            ("Eksport XLSX", "Zapisz wszystkie tabele w jednym skoroszycie.", self.choose_export_excel),
            ("Import ZIP", "Zastąp własne bazy zawartością archiwum.", self.choose_import_zip),
            ("Import folderu", "Zastąp własne bazy plikami z katalogu.", self.choose_import_folder),
            ("Tryb gościa", "Otwórz bazy z katalogu bez prawa zapisu.", self.choose_guest_folder),
        ]
        for row, (label, description, callback) in enumerate(actions):
            button = Gtk.Button(label=label)
            button.set_hexpand(False)
            button.connect("clicked", lambda _button, func=callback: func())
            text = Gtk.Label(label=description, xalign=0.0, wrap=True)
            text.set_hexpand(True)
            grid.attach(button, 0, row, 1, 1)
            grid.attach(text, 1, row, 1, 1)
        self.root_box.append(grid)

        self.guest_status = Gtk.Label(xalign=0.0, wrap=True)
        self.guest_status.add_css_class("dim-label")
        self.root_box.append(self.guest_status)
        leave_guest = Gtk.Button(label="Zakończ tryb gościa")
        leave_guest.connect("clicked", lambda _button: self.leave_guest())
        self.root_box.append(leave_guest)
        close = Gtk.Button(label="Zamknij")
        close.set_halign(Gtk.Align.END)
        close.connect("clicked", lambda _button: self.close())
        self.root_box.append(close)
        self.update_status()

    def update_status(self) -> None:
        if self.databases.guest_mode:
            self.guest_status.set_text(f"Aktywny tryb gościa: {self.databases.active_root}")
        else:
            self.guest_status.set_text(f"Własne bazy: {self.databases.own_root}")

    def _show_chooser(
        self,
        title: str,
        action: Gtk.FileChooserAction,
        accept_label: str,
        callback: Callable[[Path], None],
        suggested_name: str | None = None,
        zip_filter: bool = False,
    ) -> None:
        chooser = Gtk.FileChooserNative.new(
            title,
            self,
            action,
            accept_label,
            "Anuluj",
        )
        if suggested_name:
            chooser.set_current_name(suggested_name)
        if zip_filter:
            filter_zip = Gtk.FileFilter()
            filter_zip.set_name("Archiwa ZIP")
            filter_zip.add_pattern("*.zip")
            chooser.add_filter(filter_zip)
        self._choosers.append(chooser)

        def response(native: Gtk.FileChooserNative, response_id: int) -> None:
            try:
                if response_id == Gtk.ResponseType.ACCEPT:
                    selected = native.get_file()
                    path = Path(selected.get_path()) if selected and selected.get_path() else None
                    if path is not None:
                        callback(path)
            finally:
                if native in self._choosers:
                    self._choosers.remove(native)
                native.destroy()

        chooser.connect("response", response)
        chooser.show()

    def choose_export_zip(self) -> None:
        self._show_chooser(
            "Eksport baz do ZIP",
            Gtk.FileChooserAction.SAVE,
            "Eksportuj",
            self.export_zip,
            "sesyjka-bazy.zip",
            zip_filter=True,
        )

    def export_zip(self, destination: Path) -> None:
        try:
            output = self.databases.export_zip(destination)
            info(self, "Eksport zakończony", f"Zapisano: {output}")
        except Exception as exc:
            info(self, "Błąd eksportu", str(exc), error=True)

    def choose_export_folder(self) -> None:
        self._show_chooser(
            "Eksport baz do folderu",
            Gtk.FileChooserAction.SELECT_FOLDER,
            "Eksportuj",
            self.export_folder,
        )

    def export_folder(self, destination: Path) -> None:
        try:
            output = self.databases.export_folder(destination)
            info(self, "Eksport zakończony", f"Zapisano bazy w: {output}")
        except Exception as exc:
            info(self, "Błąd eksportu", str(exc), error=True)

    def choose_export_excel(self) -> None:
        self._show_chooser(
            "Eksport baz do XLSX",
            Gtk.FileChooserAction.SAVE,
            "Eksportuj",
            self.export_excel,
            "sesyjka-dane.xlsx",
        )

    def export_excel(self, destination: Path) -> None:
        try:
            output = self.databases.export_excel(destination)
            info(self, "Eksport zakończony", f"Zapisano: {output}")
        except Exception as exc:
            info(self, "Błąd eksportu", str(exc), error=True)

    def choose_import_zip(self) -> None:
        self._show_chooser(
            "Import baz z ZIP",
            Gtk.FileChooserAction.OPEN,
            "Wybierz",
            self.request_import,
            zip_filter=True,
        )

    def choose_import_folder(self) -> None:
        self._show_chooser(
            "Import baz z folderu",
            Gtk.FileChooserAction.SELECT_FOLDER,
            "Wybierz",
            self.request_import,
        )

    def request_import(self, source: Path) -> None:
        confirm(
            self,
            "Potwierdź import",
            "Import zastąpi odnalezione własne bazy. Przed operacją zostanie utworzona kopia zapasowa.",
            lambda: self.perform_import(source),
        )

    def perform_import(self, source: Path) -> None:
        cleanup: Path | None = None
        try:
            root, files, cleanup = self.databases.inspect_import_source(source)
            backup = self.databases.replace_own_databases(root, files)
            self.on_database_change()
            info(self, "Import zakończony", f"Zaimportowano {len(files)} baz. Kopia: {backup}")
        except Exception as exc:
            info(self, "Błąd importu", str(exc), error=True)
        finally:
            if cleanup:
                shutil.rmtree(cleanup, ignore_errors=True)

    def choose_guest_folder(self) -> None:
        self._show_chooser(
            "Wybierz folder baz gościa",
            Gtk.FileChooserAction.SELECT_FOLDER,
            "Otwórz",
            self.enter_guest,
        )

    def enter_guest(self, source: Path) -> None:
        try:
            self.databases.enter_guest_mode(source)
            self.on_guest_change()
            self.update_status()
        except Exception as exc:
            info(self, "Błąd trybu gościa", str(exc), error=True)

    def leave_guest(self) -> None:
        self.databases.leave_guest_mode()
        self.on_guest_change()
        self.update_status()
