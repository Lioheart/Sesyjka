from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

from ..dialogs import ModalWindow, confirm, info, make_entry
from ..digital_resources import (
    DTRPG_ACCOUNT_URL,
    DTRPG_LIBRARY_URL,
    DriveThruKeyStore,
    DriveThruRPGClient,
    scan_pdf_directory,
)
from ..repository import Repository
from ..widgets import Choice, ChoiceDropDown, DataTable, FormGrid, TextDropDown
from .base import CrudPage


class DigitalResourcesPage(CrudPage):
    def __init__(self, parent_window: Gtk.Window, repository: Repository) -> None:
        super().__init__(
            parent_window,
            repository,
            (
                ("ID", "id"),
                ("Pozycja RPG", "pozycja_nazwa"),
                ("Typ", "typ"),
                ("Nazwa", "nazwa"),
                ("Nazwa pliku", "plik_tekst"),
                ("Dostawca", "dostawca"),
                ("Format", "format"),
                ("Rozmiar", "rozmiar_tekst"),
                ("Lokalizacje", "lokalizacje"),
                ("Dostępność", "dostepnosc"),
            ),
            "zasób cyfrowy",
        )
        self._choosers: list[Gtk.FileChooserNative] = []
        self.open_button = Gtk.Button(label="Otwórz")
        self.open_button.set_icon_name("document-open-symbolic")
        self.open_button.set_tooltip_text("Otwórz najlepszą dostępną lokalizację zaznaczonego zasobu")
        self.open_button.connect("clicked", lambda _button: self.open_selected_resource())
        self.toolbar.insert_child_after(self.open_button, self.search)

        self.scan_button = Gtk.Button(label="Skanuj PDF")
        self.scan_button.set_icon_name("folder-open-symbolic")
        self.scan_button.set_tooltip_text("Zindeksuj pliki PDF bez kopiowania ich do Sesyjki")
        self.scan_button.connect("clicked", lambda _button: self.choose_scan_folder())
        self.toolbar.insert_child_after(self.scan_button, self.open_button)

        self.storage_button = Gtk.Button(label="Magazyny")
        self.storage_button.set_icon_name("drive-harddisk-symbolic")
        self.storage_button.set_tooltip_text("Katalogi lokalne, NAS i dyski USB")
        self.storage_button.connect("clicked", lambda _button: self.show_storages())
        self.toolbar.insert_child_after(self.storage_button, self.scan_button)

        self.drivethru_button = Gtk.Button(label="DriveThruRPG")
        self.drivethru_button.set_icon_name("network-server-symbolic")
        self.drivethru_button.set_tooltip_text("Eksperymentalnie synchronizuj metadane zakupionej biblioteki")
        self.drivethru_button.connect("clicked", lambda _button: self.show_drivethru())
        self.toolbar.insert_child_after(self.drivethru_button, self.storage_button)

    def set_read_only(self, value: bool) -> None:
        super().set_read_only(value)
        for button in (self.scan_button, self.storage_button, self.drivethru_button):
            button.set_sensitive(not value)

    def load_records(self) -> list[dict[str, Any]]:
        return self.repository.digital_resources()

    def delete_record(self, record_id: int) -> None:
        self.repository.delete_digital_resource(record_id)

    def _position_choices(self) -> list[Choice]:
        items = [
            item for item in self.repository.systems()
            if str(item.get("typ") or "").casefold() != "grupa"
        ]
        return [Choice(None, "Nieprzypisany")] + [
            Choice(int(item["id"]), f"{item.get('system_gry_nazwa') or 'Bez systemu'} · {item['nazwa']}")
            for item in sorted(items, key=lambda row: (str(row.get("system_gry_nazwa") or "").casefold(), str(row["nazwa"]).casefold()))
        ]

    def _location_description(self, item: dict[str, Any]) -> str:
        if item.get("sciezka_pelna"):
            state = "✓" if item.get("dostepny") else "✕"
            return f"{state} {item.get('magazyn_nazwa') or 'Magazyn'} · {item.get('sciezka_wzgledna') or ''}"
        return f"🌐 {item.get('typ') or 'WWW'} · {item.get('url') or ''}"

    def open_editor(self, record: dict[str, Any] | None) -> None:
        dialog = ModalWindow(
            self.parent_window,
            "Edytuj zasób cyfrowy" if record else "Dodaj zasób cyfrowy",
            width=760,
            height=680,
        )
        form = FormGrid()
        position = ChoiceDropDown(
            self._position_choices(),
            int(record["pozycja_rpg_id"]) if record and record.get("pozycja_rpg_id") is not None else None,
        )
        resource_type = TextDropDown(
            ["PDF", "VTT", "WWW", "Inne"],
            str(record.get("typ") or "PDF") if record else "PDF",
        )
        name = make_entry(record.get("nazwa") if record else "", "Nazwa zasobu")
        provider = make_entry(record.get("dostawca") if record else "", "np. Paizo, D&D Beyond, DriveThruRPG")
        format_entry = make_entry(record.get("format") if record else "", "np. PDF, Foundry VTT")
        file_title = make_entry(record.get("tytul_pliku") if record else "", "Opcjonalny tytuł pliku")
        filename = make_entry(record.get("nazwa_pliku") if record else "", "Opcjonalna techniczna nazwa pliku")
        isbn = make_entry(record.get("isbn") if record else "", "Opcjonalny ISBN")
        publisher = make_entry(record.get("wydawca") if record else "", "Opcjonalny wydawca")
        product_url = make_entry(record.get("product_url") if record else "", "https://...")
        form.add_row("Pozycja RPG", position)
        form.add_row("Typ *", resource_type)
        form.add_row("Nazwa *", name)
        form.add_row("Dostawca", provider)
        form.add_row("Format", format_entry)
        form.add_row("Tytuł pliku", file_title)
        form.add_row("Nazwa pliku", filename)
        form.add_row("ISBN", isbn)
        form.add_row("Wydawca", publisher)
        form.add_row("Strona produktu", product_url)
        dialog.add_scrolled_content(form)

        existing_locations = self.repository.resource_locations(int(record["id"])) if record else []
        if record:
            location_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            add_file = Gtk.Button(label="Dodaj plik")
            add_file.set_icon_name("document-open-symbolic")
            add_file.connect(
                "clicked",
                lambda _button: self._choose_resource_file(dialog, int(record["id"])),
            )
            add_url = Gtk.Button(label="Dodaj adres WWW")
            add_url.set_icon_name("insert-link-symbolic")
            add_url.connect(
                "clicked",
                lambda _button: self._add_url_location(dialog, int(record["id"])),
            )
            location_actions.append(add_file)
            location_actions.append(add_url)
            dialog.root_box.append(location_actions)
        else:
            hint = Gtk.Label(
                label="Po zapisaniu zasobu będzie można dodać wiele lokalizacji pliku lub adresów WWW.",
                wrap=True,
                xalign=0.0,
            )
            hint.add_css_class("dim-label")
            dialog.root_box.append(hint)
        if existing_locations:
            heading = Gtk.Label(label="Lokalizacje", xalign=0.0)
            heading.add_css_class("heading")
            dialog.root_box.append(heading)
            for location in existing_locations[:8]:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                label = Gtk.Label(label=self._location_description(location), xalign=0.0)
                label.set_hexpand(True)
                row.append(label)
                remove = Gtk.Button.new_from_icon_name("edit-delete-symbolic")
                remove.set_tooltip_text("Usuń lokalizację")
                remove.connect(
                    "clicked",
                    lambda _button, location_id=int(location["id"]): self._remove_location(dialog, location_id),
                )
                row.append(remove)
                dialog.root_box.append(row)

        def save() -> None:
            try:
                self.repository.save_digital_resource(
                    {
                        "pozycja_rpg_id": position.identifier(),
                        "typ": resource_type.text(),
                        "nazwa": name.get_text(),
                        "dostawca": provider.get_text(),
                        "format": format_entry.get_text(),
                        "nazwa_pliku": filename.get_text(),
                        "tytul_pliku": file_title.get_text(),
                        "isbn": isbn.get_text(),
                        "wydawca": publisher.get_text(),
                        "product_url": product_url.get_text(),
                        "sha256": record.get("sha256") if record else None,
                        "external_id": record.get("external_id") if record else None,
                        "rozmiar": record.get("rozmiar") if record else None,
                        "data_zakupu": record.get("data_zakupu") if record else None,
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

    def _choose_resource_file(self, parent: Gtk.Window, resource_id: int) -> None:
        chooser = Gtk.FileChooserNative.new(
            "Wybierz plik zasobu",
            parent,
            Gtk.FileChooserAction.OPEN,
            "Dodaj",
            "Anuluj",
        )
        self._choosers.append(chooser)

        def response(native: Gtk.FileChooserNative, response_id: int) -> None:
            try:
                if response_id == Gtk.ResponseType.ACCEPT:
                    selected = native.get_file()
                    if selected and selected.get_path():
                        self._add_file_location(parent, resource_id, Path(selected.get_path()))
            finally:
                if native in self._choosers:
                    self._choosers.remove(native)
                native.destroy()
        chooser.connect("response", response)
        chooser.show()

    def _add_file_location(self, parent: Gtk.Window, resource_id: int, path: Path) -> None:
        resolved = path.expanduser().resolve()
        storages = self.repository.storage_roots()
        candidates: list[tuple[int, dict[str, Any], Path]] = []
        for storage in storages:
            try:
                base = Path(str(storage.get("sciezka_bazowa") or "")).expanduser().resolve()
                relative = resolved.relative_to(base)
            except (ValueError, OSError):
                continue
            candidates.append((len(base.parts), storage, relative))
        if not candidates:
            info(
                parent,
                "Plik poza magazynami",
                "Najpierw dodaj katalog zawierający ten plik jako Magazyn. Dzięki temu Sesyjka zapisze ścieżkę względną zamiast ścieżki zależnej od konkretnego komputera.",
            )
            return
        _depth, storage, relative = max(candidates, key=lambda item: item[0])
        try:
            self.repository.save_resource_location(
                resource_id,
                {
                    "typ": "Plik",
                    "magazyn_uuid": storage["uuid"],
                    "sciezka_wzgledna": relative.as_posix(),
                    "ostatnio_dostepny": True,
                },
            )
            parent.close()
            self.refresh()
            self.notify_data_changed()
        except Exception as exc:
            info(parent, "Błąd lokalizacji", str(exc), error=True)

    def _add_url_location(self, parent: Gtk.Window, resource_id: int) -> None:
        dialog = ModalWindow(parent, "Dodaj adres WWW", width=560, height=360)
        form = FormGrid()
        kind = TextDropDown(
            ["WWW", "DriveThruRPG", "Paizo", "D&D Beyond", "Foundry VTT", "Roll20", "Fantasy Grounds", "Inne"],
            "WWW",
        )
        url = make_entry("", "https://...")
        preferred = Gtk.CheckButton(label="Preferowana lokalizacja")
        form.add_row("Typ", kind)
        form.add_row("URL *", url)
        form.add_row("", preferred)
        dialog.root_box.append(form)

        def save() -> None:
            value = url.get_text().strip()
            if not value.startswith(("https://", "http://")):
                info(dialog, "Nieprawidłowy URL", "Podaj pełny adres zaczynający się od https:// lub http://.", error=True)
                return
            try:
                self.repository.save_resource_location(
                    resource_id,
                    {"typ": kind.text(), "url": value, "preferowana": preferred.get_active()},
                )
                dialog.close()
                parent.close()
                self.refresh()
                self.notify_data_changed()
            except Exception as exc:
                info(dialog, "Błąd lokalizacji", str(exc), error=True)
        dialog.add_buttons(save, "Dodaj")
        dialog.present()

    def _remove_location(self, parent: Gtk.Window, location_id: int) -> None:
        def remove() -> None:
            try:
                self.repository.delete_resource_location(location_id)
                parent.close()
                self.refresh()
                self.notify_data_changed()
            except Exception as exc:
                info(parent, "Błąd usuwania", str(exc), error=True)
        confirm(parent, "Usuń lokalizację", "Czy usunąć tę lokalizację zasobu?", remove)

    def open_selected_resource(self) -> None:
        record = self._validated_selected_record()
        if not record:
            return
        target = self.repository.best_resource_target(int(record["id"]))
        if target is None:
            info(
                self.parent_window,
                "Brak dostępnej lokalizacji",
                "Nie znaleziono dostępnego pliku ani adresu WWW. Sprawdź magazyny albo dodaj lokalizację.",
            )
            return
        try:
            if target["kind"] == "file":
                uri = Gio.File.new_for_path(str(target["value"])).get_uri()
            else:
                uri = str(target["value"])
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except Exception as exc:
            info(self.parent_window, "Nie można otworzyć zasobu", str(exc), error=True)

    def _choose_folder(self, title: str, callback: Any) -> None:
        chooser = Gtk.FileChooserNative.new(
            title,
            self.parent_window,
            Gtk.FileChooserAction.SELECT_FOLDER,
            "Wybierz",
            "Anuluj",
        )
        self._choosers.append(chooser)

        def response(native: Gtk.FileChooserNative, response_id: int) -> None:
            try:
                if response_id == Gtk.ResponseType.ACCEPT:
                    selected = native.get_file()
                    if selected and selected.get_path():
                        callback(Path(selected.get_path()))
            finally:
                if native in self._choosers:
                    self._choosers.remove(native)
                native.destroy()
        chooser.connect("response", response)
        chooser.show()

    def choose_scan_folder(self) -> None:
        self._choose_folder("Wybierz bibliotekę PDF", self._prepare_scan)

    def _prepare_scan(self, root: Path) -> None:
        storages = self.repository.storage_roots()
        matched = next(
            (item for item in storages if Path(str(item.get("sciezka_bazowa") or "")) == root.resolve()),
            None,
        )
        if matched:
            self._run_scan(root, int(matched["id"]))
            return

        dialog = ModalWindow(self.parent_window, "Dodaj magazyn PDF", width=540, height=360)
        form = FormGrid()
        name = make_entry(root.name or "Biblioteka RPG", "Nazwa magazynu")
        kind = TextDropDown(["Lokalny", "NAS", "USB"], "Lokalny")
        path_label = Gtk.Label(label=str(root), xalign=0.0, wrap=True)
        form.add_row("Nazwa *", name)
        form.add_row("Typ", kind)
        form.add_row("Katalog", path_label)
        dialog.root_box.append(form)

        def save_and_scan() -> None:
            try:
                storage_id = self.repository.save_storage_root(
                    {"nazwa": name.get_text(), "typ": kind.text(), "sciezka_bazowa": str(root)}
                )
                dialog.close()
                self._run_scan(root, storage_id)
            except Exception as exc:
                info(dialog, "Błąd magazynu", str(exc), error=True)
        dialog.add_buttons(save_and_scan, "Dodaj i skanuj")
        dialog.present()

    def _run_scan(self, root: Path, storage_id: int) -> None:
        progress = ModalWindow(self.parent_window, "Skanowanie PDF", width=460, height=220)
        label = Gtk.Label(label=f"Skanowanie {root}…", xalign=0.0, wrap=True)
        spinner = Gtk.Spinner()
        spinner.start()
        progress.root_box.append(label)
        progress.root_box.append(spinner)
        progress.present()
        candidates = self.repository.systems()

        def worker() -> None:
            result = None
            error: Exception | None = None
            try:
                scanned = scan_pdf_directory(root, candidates)
                result = self.repository.import_scanned_pdfs(storage_id, scanned)
            except Exception as exc:
                error = exc
            GLib.idle_add(self._finish_scan, progress, result, error)
        threading.Thread(target=worker, name="sesyjka-pdf-scan", daemon=True).start()

    def _finish_scan(self, progress: Gtk.Window, result: dict[str, int] | None, error: Exception | None) -> bool:
        progress.close()
        if error is not None:
            info(self.parent_window, "Błąd skanowania", str(error), error=True)
            return False
        result = result or {}
        self.refresh()
        self.notify_data_changed()
        info(
            self.parent_window,
            "Skanowanie zakończone",
            "Znaleziono: {found}\nNowe zasoby: {created}\nJuż znane: {existing}\nPowiązane automatycznie: {linked}".format(**result),
        )
        return False

    def show_storages(self) -> None:
        dialog = ModalWindow(self.parent_window, "Magazyny zasobów", width=760, height=560)
        heading = Gtk.Label(
            label="Magazyn to logiczna biblioteka plików. Sesyjka zapisuje ścieżki względne, dzięki czemu NAS lub USB może mieć inny punkt montowania na każdym komputerze.",
            wrap=True,
            xalign=0.0,
        )
        dialog.root_box.append(heading)
        table = DataTable(
            (("ID", "id"), ("Nazwa", "nazwa"), ("Typ", "typ"), ("Katalog", "sciezka_bazowa"), ("Dostępny", "dostepny_tekst")),
            enable_filters=False,
        )
        rows = self.repository.storage_roots()
        for row in rows:
            row["dostepny_tekst"] = "Tak" if row.get("dostepny") else "Nie"
        table.set_records(rows)
        dialog.add_scrolled_content(table)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add = Gtk.Button(label="Dodaj magazyn")
        add.add_css_class("suggested-action")
        missing = self.repository.unmapped_storage_roots()
        map_missing = Gtk.Button(label=f"Powiąż brakujące ({len(missing)})")
        map_missing.set_sensitive(bool(missing))
        map_missing.set_tooltip_text("Powiąż magazyn zsynchronizowany z innego urządzenia z lokalnym katalogiem")
        delete = Gtk.Button(label="Usuń")
        delete.add_css_class("destructive-action")
        close = Gtk.Button(label="Zamknij")
        buttons.append(add)
        buttons.append(map_missing)
        buttons.append(delete)
        buttons.append(close)
        dialog.root_box.append(buttons)
        add.connect("clicked", lambda _button: self._choose_folder("Wybierz katalog magazynu", lambda path: self._add_storage_from_path(dialog, path)))
        map_missing.connect("clicked", lambda _button: self._map_missing_storage(dialog, missing))
        delete.connect("clicked", lambda _button: self._delete_storage_selected(dialog, table))
        close.connect("clicked", lambda _button: dialog.close())
        dialog.present()

    def _map_missing_storage(self, parent: Gtk.Window, missing: list[dict[str, Any]]) -> None:
        if not missing:
            return
        dialog = ModalWindow(parent, "Powiąż magazyn z tego urządzenia", width=620, height=430)
        form = FormGrid()
        choices = [Choice(index, f"{item['uuid']} · {item['count']} lokalizacji") for index, item in enumerate(missing)]
        selected = ChoiceDropDown(choices, 0)
        name = make_entry("Biblioteka RPG", "Nazwa magazynu na tym urządzeniu")
        kind = TextDropDown(["Lokalny", "NAS", "USB"], "NAS")
        path_value = Gtk.Label(label="Nie wybrano katalogu", xalign=0.0, wrap=True)
        chosen: dict[str, Path | None] = {"path": None}
        choose = Gtk.Button(label="Wybierz katalog")
        choose.connect(
            "clicked",
            lambda _button: self._choose_folder(
                "Wybierz lokalny katalog odpowiadający magazynowi",
                lambda path: (chosen.__setitem__("path", path), path_value.set_text(str(path))),
            ),
        )
        form.add_row("Brakujące UUID", selected)
        form.add_row("Nazwa", name)
        form.add_row("Typ", kind)
        form.add_row("Katalog", path_value)
        form.add_row("", choose)
        dialog.root_box.append(form)

        def save() -> None:
            index = selected.identifier()
            if index is None or chosen["path"] is None:
                info(dialog, "Brak danych", "Wybierz brakujący magazyn i lokalny katalog.", error=True)
                return
            try:
                self.repository.save_storage_root(
                    {
                        "uuid": missing[int(index)]["uuid"],
                        "nazwa": name.get_text(),
                        "typ": kind.text(),
                        "sciezka_bazowa": str(chosen["path"]),
                    }
                )
                dialog.close()
                parent.close()
                self.show_storages()
                self.refresh()
            except Exception as exc:
                info(dialog, "Błąd mapowania", str(exc), error=True)
        dialog.add_buttons(save, "Powiąż")
        dialog.present()

    def _add_storage_from_path(self, parent: Gtk.Window, path: Path) -> None:
        form_dialog = ModalWindow(parent, "Nowy magazyn", width=520, height=340)
        form = FormGrid()
        name = make_entry(path.name or "Biblioteka RPG")
        kind = TextDropDown(["Lokalny", "NAS", "USB"], "Lokalny")
        form.add_row("Nazwa *", name)
        form.add_row("Typ", kind)
        form.add_row("Katalog", Gtk.Label(label=str(path), xalign=0.0, wrap=True))
        form_dialog.root_box.append(form)

        def save() -> None:
            try:
                self.repository.save_storage_root({"nazwa": name.get_text(), "typ": kind.text(), "sciezka_bazowa": str(path)})
                form_dialog.close()
                parent.close()
                self.show_storages()
                self.refresh()
                self.notify_data_changed()
            except Exception as exc:
                info(form_dialog, "Błąd zapisu", str(exc), error=True)
        form_dialog.add_buttons(save)
        form_dialog.present()

    def _delete_storage_selected(self, parent: Gtk.Window, table: DataTable) -> None:
        record = table.selected_record()
        if not record:
            info(parent, "Brak zaznaczenia", "Zaznacz magazyn.")
            return
        def delete() -> None:
            try:
                self.repository.delete_storage_root(int(record["id"]))
                parent.close()
                self.show_storages()
            except Exception as exc:
                info(parent, "Błąd usuwania", str(exc), error=True)
        confirm(parent, "Usuń magazyn", f"Czy usunąć magazyn: {record.get('nazwa')}?", delete)

    def show_drivethru(self) -> None:
        dialog = ModalWindow(self.parent_window, "DriveThruRPG", width=620, height=480)
        explanation = Gtk.Label(
            label=(
                "Eksperymentalna synchronizacja biblioteki DriveThruRPG. Importowane są metadane, nazwy plików, sumy kontrolne i linki do produktu. Sesyjka nie pobiera automatycznie dużych plików PDF.\n\n"
                "W DriveThruRPG utwórz Application Key i włącz dla niego My Library Access. Klucz jest przechowywany tylko lokalnie z prawami 0600 i nie jest synchronizowany do Sesyjka Cloud."
            ),
            wrap=True,
            xalign=0.0,
        )
        dialog.root_box.append(explanation)
        form = FormGrid()
        key_store = DriveThruKeyStore()
        key = Gtk.PasswordEntry()
        key.set_show_peek_icon(True)
        key.set_text(key_store.load())
        form.add_row("Application Key", key)
        dialog.root_box.append(form)

        links = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        account = Gtk.Button(label="Ustawienia konta")
        account.connect("clicked", lambda _button: webbrowser.open(DTRPG_ACCOUNT_URL))
        library = Gtk.Button(label="Otwórz My Library")
        library.connect("clicked", lambda _button: webbrowser.open(DTRPG_LIBRARY_URL))
        scan_downloads = Gtk.Button(label="Skanuj pobrane PDF")
        scan_downloads.set_tooltip_text("Stabilna alternatywa: zindeksuj katalog pobierania DriveThruRPG")
        scan_downloads.connect(
            "clicked",
            lambda _button: (dialog.close(), self.choose_scan_folder()),
        )
        links.append(account)
        links.append(library)
        links.append(scan_downloads)
        dialog.root_box.append(links)

        status = Gtk.Label(label="", xalign=0.0, wrap=True)
        status.add_css_class("dim-label")
        dialog.root_box.append(status)
        sync = Gtk.Button(label="Synchronizuj bibliotekę")
        sync.add_css_class("suggested-action")
        dialog.root_box.append(sync)
        close = Gtk.Button(label="Zamknij")
        close.set_halign(Gtk.Align.END)
        close.connect("clicked", lambda _button: dialog.close())
        dialog.root_box.append(close)

        def start(_button: Gtk.Button) -> None:
            application_key = key.get_text().strip()
            if not application_key:
                info(dialog, "Brak klucza", "Podaj Application Key DriveThruRPG.", error=True)
                return
            key_store.save(application_key)
            sync.set_sensitive(False)
            status.set_text("Pobieranie listy zakupów DriveThruRPG…")

            def worker() -> None:
                result = None
                error: Exception | None = None
                try:
                    items = DriveThruRPGClient(application_key).library()
                    result = self.repository.import_drivethru_library(items)
                except Exception as exc:
                    error = exc
                GLib.idle_add(finish, result, error)

            def finish(result: dict[str, int] | None, error: Exception | None) -> bool:
                sync.set_sensitive(True)
                if error is not None:
                    status.set_text("Synchronizacja nie powiodła się.")
                    info(dialog, "DriveThruRPG", str(error), error=True)
                    return False
                result = result or {}
                status.set_text(
                    "Znaleziono: {found}, nowe: {created}, zaktualizowane: {updated}, powiązane z pozycją RPG: {linked}.".format(**result)
                )
                self.refresh()
                self.notify_data_changed()
                return False

            threading.Thread(target=worker, name="sesyjka-drivethrurpg", daemon=True).start()

        sync.connect("clicked", start)
        dialog.present()
