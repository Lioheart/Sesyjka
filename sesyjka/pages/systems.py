from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
import re
from threading import Thread
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from ..book_lookup import BookLookupResult, download_cover, lookup_book, normalize_isbn
from ..dialogs import ModalWindow, confirm, info, make_entry
from ..repository import Repository
from ..validation import LANGUAGE_CHOICES, is_valid_isbn, normalize_language_choice
from ..widgets import Choice, ChoiceDropDown, FormGrid, TextDropDown
from .base import CrudPage


ITEM_TYPES = (
    "Podręcznik Główny",
    "Suplement",
    "Inne",
    "Grupa",
)


SUPPLEMENT_TYPES = (
    "Scenariusz/kampania",
    "Rozwinięcie zasad",
    "Moduł",
    "Lorebook/Sourcebook",
    "Bestiariusz",
    "Starter/Zestaw Startowy",
)


class SystemsPage(CrudPage):
    def __init__(self, parent_window: Gtk.Window, repository: Repository) -> None:
        super().__init__(
            parent_window,
            repository,
            (
                ("ID", "id"),
                ("Nazwa", "nazwa"),
                ("Typ", "typ"),
                ("Podgrupa", "typ_suplementu"),
                ("Grupa", "system_glowny_nazwa"),
                ("Wydawca", "wydawca_nazwa"),
                ("Język", "jezyk"),
                ("Fiz.", "fizyczny_tekst"),
                ("PDF", "pdf_tekst"),
                ("VTT", "vtt"),
                ("Status gry", "status_gra"),
                ("Kolekcja", "status_kolekcja"),
                ("Rok", "rok_wydania"),
            ),
            "pozycję RPG",
            grouped=True,
            tree_key="nazwa",
        )
        self.table.set_context_actions(self._context_edit, self._context_delete)
        self.game_system_button = Gtk.Button(label="Dodaj system gry")
        self.game_system_button.connect("clicked", lambda _button: self.open_game_system_editor())
        toolbar = self.get_first_child()
        if isinstance(toolbar, Gtk.Box):
            toolbar.insert_child_after(self.game_system_button, self.search)

    def set_read_only(self, value: bool) -> None:
        super().set_read_only(value)
        self.game_system_button.set_sensitive(not value)

    def _publisher_choices(self) -> list[Choice]:
        return [
            Choice(None, "Brak"),
            *[
                Choice(int(row["id"]), str(row["nazwa"]))
                for row in self.repository.publishers()
            ],
        ]

    def load_records(self) -> list[dict[str, Any]]:
        positions = self.repository.systems()
        positions_by_game: dict[int, list[dict[str, Any]]] = defaultdict(list)
        orphaned: list[dict[str, Any]] = []

        for record in positions:
            child = dict(record)
            child["fizyczny_tekst"] = "Tak" if record.get("fizyczny") else ""
            child["pdf_tekst"] = "Tak" if record.get("pdf") else ""
            child["_context_enabled"] = True
            child["_is_entity"] = True
            game_id = record.get("system_gry_id")
            if game_id is None:
                orphaned.append(child)
            else:
                positions_by_game[int(game_id)].append(child)

        def build_book_tree(records: list[dict[str, Any]], base_depth: int = 1) -> list[dict[str, Any]]:
            by_id = {int(record["id"]): record for record in records}
            children_by_parent: dict[int, list[dict[str, Any]]] = defaultdict(list)
            roots: list[dict[str, Any]] = []

            for record in records:
                parent_id = record.get("system_glowny_id")
                record_id = int(record["id"])
                if parent_id is not None and int(parent_id) in by_id and int(parent_id) != record_id:
                    children_by_parent[int(parent_id)].append(record)
                else:
                    roots.append(record)

            visited: set[int] = set()

            def build(record: dict[str, Any], depth: int, path: set[int]) -> dict[str, Any]:
                record_id = int(record["id"])
                node = dict(record)
                node["_depth"] = depth
                node["_is_entity"] = True
                node["_context_enabled"] = True
                visited.add(record_id)
                if record_id in path:
                    node["_children"] = []
                    return node

                next_path = {*path, record_id}
                descendants = [
                    build(child, depth + 1, next_path)
                    for child in children_by_parent.get(record_id, [])
                    if int(child["id"]) not in next_path
                ]
                node["_children"] = descendants
                if descendants:
                    node["_is_group"] = True
                    node["_group_id"] = f"book:{record_id}"
                return node

            tree = [build(root, base_depth, set()) for root in roots]
            # Uszkodzone lub cykliczne odwołania nie mogą ukryć rekordów.
            for record in records:
                if int(record["id"]) not in visited:
                    tree.append(build(record, base_depth, set()))
            return tree

        groups: list[dict[str, Any]] = []
        for game in self.repository.game_systems():
            game_id = int(game["id"])
            game_records = positions_by_game.pop(game_id, [])
            children = build_book_tree(game_records)
            groups.append(
                {
                    "id": f"S{game_id}",
                    "nazwa": str(game["nazwa"]),
                    "typ": "System RPG",
                    "typ_suplementu": f"{game.get('liczba_pozycji', 0)} pozycji",
                    "wydawca_nazwa": game.get("wydawca_nazwa", ""),
                    "jezyk": game.get("jezyk", ""),
                    "_is_group": True,
                    "_is_entity": False,
                    "_record_kind": "game_system",
                    "game_system_id": game_id,
                    "wydawca_id": game.get("wydawca_id"),
                    "notatki": game.get("notatki", ""),
                    "_depth": 0,
                    "_group_id": f"system:{game_id}",
                    "_context_enabled": True,
                    "_children": children,
                }
            )

        for missing_game_id, records in sorted(positions_by_game.items()):
            children = build_book_tree(records)
            groups.append(
                {
                    "id": f"S{missing_game_id}",
                    "nazwa": f"Nieznany system #{missing_game_id}",
                    "typ": "System RPG",
                    "typ_suplementu": f"{len(records)} pozycji",
                    "_is_group": True,
                    "_is_entity": False,
                    "_depth": 0,
                    "_group_id": f"missing:{missing_game_id}",
                    "_context_enabled": False,
                    "_children": children,
                }
            )

        if orphaned:
            groups.append(
                {
                    "id": "-",
                    "nazwa": "Bez przypisanego systemu",
                    "typ": "Grupa",
                    "typ_suplementu": f"{len(orphaned)} pozycji",
                    "_is_group": True,
                    "_is_entity": False,
                    "_depth": 0,
                    "_group_id": "orphans",
                    "_context_enabled": False,
                    "_children": build_book_tree(orphaned),
                }
            )
        return groups

    def delete_record(self, record_id: int) -> None:
        self.repository.delete_system(record_id)

    def _context_edit(self, record: dict[str, Any]) -> None:
        if record.get("_record_kind") == "game_system":
            self.open_game_system_editor(record)
        else:
            self.open_editor(record)

    def _context_delete(self, record: dict[str, Any]) -> None:
        if record.get("_record_kind") != "game_system":
            self.request_delete(record)
            return
        game_system_id = int(record["game_system_id"])
        confirm(
            self.parent_window,
            "Usuń system RPG",
            f"Czy usunąć system: {record.get('nazwa', '')}?",
            lambda: self._delete_game_system_confirmed(game_system_id),
        )

    def _delete_game_system_confirmed(self, game_system_id: int) -> None:
        try:
            self.repository.delete_game_system(game_system_id)
            self.refresh()
            self.notify_data_changed()
        except Exception as exc:
            info(self.parent_window, "Błąd usuwania", str(exc), error=True)

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
            lambda _button: self.open_quick_publisher_editor(dialog_parent, refresh_after_add),
        )
        return row, selector

    def open_quick_publisher_editor(
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

    def open_game_system_editor(self, record: dict[str, Any] | None = None) -> None:
        dialog = ModalWindow(
            self.parent_window,
            "Edytuj system gry" if record else "Dodaj system gry",
            width=560,
            height=360,
        )
        form = FormGrid()
        name = make_entry(record.get("nazwa") if record else "", "Nazwa systemu gry")
        notes = Gtk.TextView()
        notes.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        notes.set_size_request(-1, 120)
        if record and record.get("notatki"):
            notes.get_buffer().set_text(str(record["notatki"]))
        form.add_row("Nazwa *", name)
        form.add_row("Notatki", notes)
        dialog.add_scrolled_content(form)

        def save() -> None:
            buffer = notes.get_buffer()
            text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
            try:
                self.repository.save_game_system(
                    {
                        "nazwa": name.get_text(),
                        "notatki": text,
                    },
                    int(record["game_system_id"]) if record else None,
                )
                dialog.close()
                self.refresh()
                self.notify_data_changed()
            except Exception as exc:
                info(dialog, "Błąd zapisu", str(exc), error=True)

        dialog.add_buttons(save)
        dialog.present()

    def open_editor(self, record: dict[str, Any] | None) -> None:
        if record and record.get("_is_group") and not record.get("_is_entity"):
            return
        dialog = ModalWindow(
            self.parent_window,
            "Edytuj pozycję RPG" if record else "Dodaj pozycję RPG",
            width=1160,
            height=860,
        )
        form = FormGrid()
        name = make_entry(record.get("nazwa") if record else "", "Nazwa pozycji")
        raw_type = str(record.get("typ") or "Podręcznik Główny") if record else "Podręcznik Główny"
        item_types_by_key = {value.casefold(): value for value in ITEM_TYPES}
        selected_type = item_types_by_key.get(raw_type.casefold(), "Inne")
        item_type = TextDropDown(ITEM_TYPES, selected_type)
        game_choices = [
            Choice(None, "Brak"),
            *[Choice(int(row["id"]), str(row["nazwa"])) for row in self.repository.game_systems()],
        ]
        game_system = ChoiceDropDown(game_choices, record.get("system_gry_id") if record else None)

        group_records = [
            row
            for row in self.repository.systems()
            if str(row.get("typ") or "").casefold() == "grupa"
            and (record is None or int(row["id"]) != int(record["id"]))
        ]
        groups_by_system: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for group_record in group_records:
            group_system_id = group_record.get("system_gry_id")
            if group_system_id is not None:
                groups_by_system[int(group_system_id)].append(group_record)

        initial_group_id = record.get("system_glowny_id") if record else None
        valid_group_ids = {int(row["id"]) for row in group_records}
        if initial_group_id is not None and int(initial_group_id) not in valid_group_ids:
            initial_group_id = None
        group_selector = ChoiceDropDown([Choice(None, "Brak")], initial_group_id)

        publisher_row, publisher = self._publisher_selector(
            dialog,
            record.get("wydawca_id") if record else None,
        )
        language = TextDropDown(
            LANGUAGE_CHOICES,
            normalize_language_choice(record.get("jezyk") if record else "PL"),
        )

        raw_supplement_types = str(record.get("typ_suplementu") or "") if record else ""
        existing_supplement_types = [
            value.strip()
            for value in re.split(r"[;,|\n]+", raw_supplement_types)
            if value.strip()
        ]
        standard_by_key = {value.casefold(): value for value in SUPPLEMENT_TYPES}
        selected_supplement_keys = {value.casefold() for value in existing_supplement_types}
        legacy_supplement_types = [
            value for value in existing_supplement_types if value.casefold() not in standard_by_key
        ]
        supplement_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        supplement_box.add_css_class("supplement-type-list")
        supplement_checks: list[tuple[str, Gtk.CheckButton]] = []
        for supplement_label in (*SUPPLEMENT_TYPES, *legacy_supplement_types):
            check = Gtk.CheckButton(label=supplement_label)
            check.set_active(supplement_label.casefold() in selected_supplement_keys)
            supplement_box.append(check)
            supplement_checks.append((supplement_label, check))

        game_status = TextDropDown(
            ["Nie grane", "Grane"],
            str(record.get("status_gra") or "Nie grane") if record else "Nie grane",
        )
        collection_status = TextDropDown(
            ["W kolekcji", "Na sprzedaż", "Sprzedane", "Nieposiadane", "Do kupienia", "Pożyczone"],
            str(record.get("status_kolekcja") or "W kolekcji") if record else "W kolekcji",
        )

        physical = Gtk.CheckButton(label="Egzemplarz fizyczny")
        physical.set_active(bool(record and record.get("fizyczny")))
        vtt_enabled = Gtk.CheckButton(label="VTT")
        vtt_enabled.set_active(bool(record and record.get("vtt")))
        pdf = Gtk.CheckButton(label="PDF")
        pdf.set_active(bool(record and record.get("pdf")))
        formats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        formats.append(physical)
        formats.append(vtt_enabled)
        formats.append(pdf)

        vtt_platform = make_entry(record.get("vtt") if record else "", "Np. Foundry VTT, Roll20")
        physical_value = record.get("cena_fiz") if record else ""
        pdf_value = record.get("cena_pdf") if record else ""
        vtt_value = record.get("cena_vtt") if record else ""
        legacy_total = record.get("cena_zakupu") if record else None
        selected_formats = sum((physical.get_active(), pdf.get_active(), vtt_enabled.get_active()))
        if legacy_total not in (None, "") and all(value in (None, "") for value in (physical_value, pdf_value, vtt_value)) and selected_formats == 1:
            if physical.get_active():
                physical_value = legacy_total
            elif pdf.get_active():
                pdf_value = legacy_total
            else:
                vtt_value = legacy_total
        price_physical = make_entry(physical_value, "Cena fizyczna")
        price_pdf = make_entry(pdf_value, "Cena PDF")
        price_vtt = make_entry(vtt_value, "Cena VTT")
        purchase_price = make_entry("", "Wyliczana automatycznie")
        purchase_price.set_editable(False)
        purchase_price.set_can_focus(False)
        currency = make_entry(
            record.get("waluta_zakupu") if record else "PLN",
            "PLN, USD, EUR lub GBP",
        )
        currency.set_tooltip_text("Najczęściej używane kody: PLN, USD, EUR lub GBP")
        currency.set_icon_from_icon_name(
            Gtk.EntryIconPosition.SECONDARY,
            "dialog-information-symbolic",
        )
        currency.set_icon_tooltip_text(
            Gtk.EntryIconPosition.SECONDARY,
            "Najczęściej używane kody walut: PLN, USD, EUR lub GBP",
        )
        sale_price = make_entry(record.get("cena_sprzedazy") if record else "", "Cena sprzedaży")
        sale_currency = make_entry(record.get("waluta_sprzedazy") if record else "PLN", "Waluta sprzedaży")
        year = make_entry(record.get("rok_wydania") if record else "", "RRRR")
        isbn = make_entry(record.get("isbn") if record else "", "ISBN")

        form.add_row("Nazwa *", name)
        form.add_row("Typ *", item_type)
        form.add_row("System RPG *", game_system)
        form.add_row("Grupa", group_selector)
        form.add_row("Wydawca", publisher_row)
        form.add_row("Formaty", formats)
        form.add_row("Język", language)
        form.add_row("Status gry", game_status)
        form.add_row("Status kolekcji", collection_status)
        form.add_row("Rok wydania", year)
        form.add_row("Numer ISBN", isbn)
        form.add_row("Podgrupa suplementu", supplement_box)
        form.add_row("Platforma VTT", vtt_platform)
        form.add_row("Cena fizyczna", price_physical)
        form.add_row("Cena VTT", price_vtt)
        form.add_row("Cena PDF", price_pdf)
        form.add_row("Cena łączna", purchase_price)
        form.add_row("Waluta zakupu", currency)
        form.add_row("Cena sprzedaży", sale_price)
        form.add_row("Waluta sprzedaży", sale_currency)

        form_scroller = Gtk.ScrolledWindow()
        form_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        form_scroller.set_vexpand(True)
        form_scroller.set_hexpand(True)
        form_scroller.set_child(form)

        preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        preview.add_css_class("isbn-preview")
        preview.set_margin_start(18)
        preview.set_margin_end(6)
        preview.set_margin_top(4)
        preview.set_margin_bottom(4)
        preview.set_size_request(360, -1)

        preview_heading = Gtk.Label(label="Dane z ISBN", xalign=0.0)
        preview_heading.add_css_class("title-3")
        preview.append(preview_heading)

        cover_stack = Gtk.Stack()
        cover_stack.set_vexpand(True)
        cover_stack.set_size_request(300, 390)
        cover_picture = Gtk.Picture()
        cover_picture.set_can_shrink(True)
        cover_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        cover_picture.set_halign(Gtk.Align.FILL)
        cover_picture.set_valign(Gtk.Align.FILL)
        cover_stack.add_named(cover_picture, "cover")

        cover_placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        cover_placeholder.set_halign(Gtk.Align.CENTER)
        cover_placeholder.set_valign(Gtk.Align.CENTER)
        placeholder_icon = Gtk.Image.new_from_icon_name("image-x-generic-symbolic")
        placeholder_icon.set_pixel_size(96)
        placeholder_label = Gtk.Label(label="Brak okładki")
        placeholder_label.add_css_class("dim-label")
        cover_placeholder.append(placeholder_icon)
        cover_placeholder.append(placeholder_label)
        cover_stack.add_named(cover_placeholder, "placeholder")
        cover_stack.set_visible_child_name("placeholder")
        preview.append(cover_stack)

        isbn_title = Gtk.Label(label="Wpisz ISBN i pobierz dane", wrap=True, xalign=0.5)
        isbn_title.add_css_class("title-4")
        isbn_title.set_justify(Gtk.Justification.CENTER)
        isbn_title.set_selectable(True)
        preview.append(isbn_title)

        isbn_year = Gtk.Label(label="", xalign=0.5)
        isbn_year.add_css_class("dim-label")
        preview.append(isbn_year)

        isbn_publisher = Gtk.Label(label="", wrap=True, xalign=0.5)
        isbn_publisher.add_css_class("dim-label")
        isbn_publisher.set_justify(Gtk.Justification.CENTER)
        isbn_publisher.set_selectable(True)
        preview.append(isbn_publisher)

        online_price = Gtk.Label(label="", wrap=True, xalign=0.0)
        online_price.set_selectable(True)
        preview.append(online_price)

        lookup_source = Gtk.Label(label="", wrap=True, xalign=0.0)
        lookup_source.add_css_class("dim-label")
        preview.append(lookup_source)

        lookup_status = Gtk.Label(label="", wrap=True, xalign=0.0)
        lookup_status.add_css_class("dim-label")
        preview.append(lookup_status)

        lookup_spinner = Gtk.Spinner()
        lookup_spinner.set_halign(Gtk.Align.CENTER)
        preview.append(lookup_spinner)

        lookup_button = Gtk.Button(label="Pobierz z ISBN")
        preview.append(lookup_button)

        apply_metadata_button = Gtk.Button(label="Użyj danych z ISBN")
        apply_metadata_button.set_visible(False)
        preview.append(apply_metadata_button)

        apply_price_button = Gtk.Button(label="Użyj ceny online")
        apply_price_button.set_visible(False)
        preview.append(apply_price_button)

        preview_note = Gtk.Label(
            label=(
                "Metadane i okładka są pobierane jednorazowo na żądanie. "
                "Cena online jest informacyjna i może dotyczyć wydania cyfrowego."
            ),
            wrap=True,
            xalign=0.0,
        )
        preview_note.add_css_class("caption")
        preview_note.add_css_class("dim-label")
        preview.append(preview_note)

        split = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        split.set_wide_handle(True)
        split.set_vexpand(True)
        split.set_hexpand(True)
        split.set_start_child(form_scroller)
        split.set_end_child(preview)
        split.set_position(690)
        dialog.root_box.append(split)

        lookup_state: dict[str, Any] = {"generation": 0, "result": None}

        def parse_price(entry: Gtk.Entry) -> float:
            text = entry.get_text().strip().replace(",", ".")
            if not text:
                return 0.0
            try:
                return max(float(text), 0.0)
            except ValueError:
                return 0.0

        def local_prices_missing() -> bool:
            return all(
                parse_price(entry) <= 0.0
                for entry in (price_physical, price_pdf, price_vtt)
            )

        def matching_publisher_id(label: str) -> int | None:
            wanted = str(label or "").strip().casefold()
            if not wanted:
                return None
            for row in self.repository.publishers():
                if str(row.get("nazwa") or "").strip().casefold() == wanted:
                    return int(row["id"])
            return None

        def apply_lookup_metadata(_button: Gtk.Button | None = None) -> None:
            result = lookup_state.get("result")
            if not isinstance(result, BookLookupResult):
                return
            if result.title:
                name.set_text(result.title)
            if result.published_year:
                year.set_text(result.published_year)
            if result.publisher:
                publisher_id = matching_publisher_id(result.publisher)
                if publisher_id is not None:
                    publisher.set_choices(self._publisher_choices(), publisher_id)
                else:
                    info(
                        dialog,
                        "Wydawca nie istnieje w bazie",
                        f"Znaleziono wydawcę: {result.publisher}. "
                        "Dodaj go przyciskiem ‘Dodaj wydawcę’, jeżeli chcesz przypisać go do pozycji.",
                    )

        def apply_lookup_price(_button: Gtk.Button | None = None) -> None:
            result = lookup_state.get("result")
            if not isinstance(result, BookLookupResult) or not result.has_price():
                return
            targets: list[tuple[str, Gtk.Entry]] = []
            if physical.get_active():
                targets.append(("fizyczną", price_physical))
            if pdf.get_active():
                targets.append(("PDF", price_pdf))
            if vtt_enabled.get_active():
                targets.append(("VTT", price_vtt))

            target: Gtk.Entry | None = None
            if result.price_kind == "e-book" and pdf.get_active():
                target = price_pdf
            elif len(targets) == 1:
                target = targets[0][1]
            if target is None:
                info(
                    dialog,
                    "Wybierz format ceny",
                    "Cena internetowa jest tylko wskazówką. Zaznacz dokładnie jeden "
                    "format albo zaznacz PDF dla ceny e-booka, a następnie użyj ceny ponownie.",
                )
                return

            target.set_text(f"{float(result.price_amount):.2f}")
            if result.price_currency:
                currency.set_text(result.price_currency)
            update_total()
            apply_price_button.set_visible(False)

        def finish_isbn_lookup(
            generation: int,
            result: BookLookupResult,
            cover_path: str,
        ) -> bool:
            if generation != int(lookup_state.get("generation", 0)):
                return False
            if not dialog.get_visible():
                return False
            lookup_spinner.stop()
            lookup_button.set_sensitive(True)

            lookup_state["result"] = result
            if cover_path:
                cover_picture.set_filename(cover_path)
                cover_stack.set_visible_child_name("cover")
            else:
                cover_stack.set_visible_child_name("placeholder")

            isbn_title.set_text(result.title or "Nie znaleziono tytułu")
            isbn_year.set_text(
                f"Rok wydania: {result.published_year}"
                if result.published_year
                else "Rok wydania: brak danych"
            )
            if result.publisher:
                publisher_id = matching_publisher_id(result.publisher)
                suffix = "" if publisher_id is not None else " (brak w bazie wydawców)"
                isbn_publisher.set_text(f"Wydawca: {result.publisher}{suffix}")
                if publisher.identifier() is None and publisher_id is not None:
                    publisher.set_choices(self._publisher_choices(), publisher_id)
            else:
                isbn_publisher.set_text("Wydawca: brak danych")
            if result.has_price():
                kind = f", {result.price_kind}" if result.price_kind else ""
                online_price.set_text(
                    f"Cena online: {float(result.price_amount):.2f} "
                    f"{result.price_currency}{kind}"
                )
            else:
                online_price.set_text("Cena online: brak danych")

            sources = ", ".join(result.metadata_sources)
            if result.price_source and result.price_source not in result.metadata_sources:
                sources = ", ".join(filter(None, (sources, result.price_source)))
            lookup_source.set_text(f"Źródło: {sources}" if sources else "")

            if result.title and not name.get_text().strip():
                name.set_text(result.title)
            if result.published_year and not year.get_text().strip():
                year.set_text(result.published_year)

            matched_publisher = matching_publisher_id(result.publisher) if result.publisher else None
            can_apply_metadata = bool(
                (result.title and result.title != name.get_text().strip())
                or (result.published_year and result.published_year != year.get_text().strip())
                or (matched_publisher is not None and matched_publisher != publisher.identifier())
                or (result.publisher and matched_publisher is None)
            )
            apply_metadata_button.set_visible(can_apply_metadata)
            apply_price_button.set_visible(result.has_price() and local_prices_missing())
            if result.has_metadata() or result.has_price():
                lookup_status.set_text("Pobieranie zakończone.")
            else:
                lookup_status.set_text("Nie znaleziono danych dla podanego ISBN.")
            return False

        def start_isbn_lookup(_button: Gtk.Button | None = None) -> None:
            isbn_value = normalize_isbn(isbn.get_text())
            if not isbn_value:
                lookup_status.set_text("Wpisz numer ISBN.")
                return

            lookup_state["generation"] = int(lookup_state.get("generation", 0)) + 1
            generation = int(lookup_state["generation"])
            lookup_button.set_sensitive(False)
            lookup_spinner.start()
            lookup_status.set_text("Pobieranie danych z internetu…")
            apply_metadata_button.set_visible(False)
            apply_price_button.set_visible(False)

            def worker() -> None:
                result = lookup_book(isbn_value, timeout=6.0)
                cover = download_cover(result, timeout=6.0)
                GLib.idle_add(
                    finish_isbn_lookup,
                    generation,
                    result,
                    str(cover) if cover else "",
                )

            Thread(
                target=worker,
                name=f"sesyjka-isbn-{isbn_value}",
                daemon=True,
            ).start()

        def on_isbn_changed(_entry: Gtk.Entry) -> None:
            result = lookup_state.get("result")
            if isinstance(result, BookLookupResult) and result.isbn == normalize_isbn(isbn.get_text()):
                return
            lookup_state["result"] = None
            lookup_state["generation"] = int(lookup_state.get("generation", 0)) + 1
            lookup_spinner.stop()
            lookup_button.set_sensitive(True)
            cover_stack.set_visible_child_name("placeholder")
            isbn_title.set_text("Wpisz ISBN i pobierz dane")
            isbn_year.set_text("")
            isbn_publisher.set_text("")
            online_price.set_text("")
            lookup_source.set_text("")
            lookup_status.set_text("")
            apply_metadata_button.set_visible(False)
            apply_price_button.set_visible(False)

        lookup_button.connect("clicked", start_isbn_lookup)
        apply_metadata_button.connect("clicked", apply_lookup_metadata)
        apply_price_button.connect("clicked", apply_lookup_price)
        isbn.connect("changed", on_isbn_changed)
        isbn.connect("activate", start_isbn_lookup)

        def update_total(*_args: object) -> None:
            total = 0.0
            if physical.get_active():
                total += parse_price(price_physical)
            if pdf.get_active():
                total += parse_price(price_pdf)
            if vtt_enabled.get_active():
                total += parse_price(price_vtt)
            purchase_price.set_text(f"{total:.2f}")

        def refresh_group_choices(*_args: object) -> None:
            current_group_id = group_selector.identifier()
            selected_system_id = game_system.identifier()
            available_groups = (
                groups_by_system.get(int(selected_system_id), [])
                if selected_system_id is not None
                else []
            )
            choices = [
                Choice(None, "Brak"),
                *[
                    Choice(int(group["id"]), str(group["nazwa"]))
                    for group in sorted(
                        available_groups,
                        key=lambda item: str(item.get("nazwa") or "").casefold(),
                    )
                ],
            ]
            selected_id = current_group_id
            if (
                selected_id is None
                and len(group_selector.choices) == 1
                and initial_group_id is not None
            ):
                selected_id = int(initial_group_id)
            group_selector.set_choices(choices, selected_id)

        def update_visibility(*_args: object) -> None:
            form.set_row_visible(group_selector, item_type.text() != "Grupa")
            form.set_row_visible(supplement_box, item_type.text() == "Suplement")
            form.set_row_visible(vtt_platform, vtt_enabled.get_active())
            form.set_row_visible(price_physical, physical.get_active())
            form.set_row_visible(price_pdf, pdf.get_active())
            form.set_row_visible(price_vtt, vtt_enabled.get_active())
            selling = collection_status.text() in {"Na sprzedaż", "Sprzedane"}
            form.set_row_visible(sale_price, selling)
            form.set_row_visible(sale_currency, selling)
            update_total()

        for toggle in (physical, pdf, vtt_enabled):
            toggle.connect("toggled", update_visibility)
        collection_status.connect("notify::selected", update_visibility)
        item_type.connect("notify::selected", update_visibility)
        game_system.connect("notify::selected", refresh_group_choices)
        for entry in (price_physical, price_pdf, price_vtt):
            entry.connect("changed", update_total)
        refresh_group_choices()
        update_visibility()

        def build_payload() -> dict[str, Any]:
            parent_id = (
                group_selector.identifier()
                if item_type.text() != "Grupa"
                else None
            )
            selected_game_system_id = game_system.identifier()
            if selected_game_system_id is None:
                raise ValueError("Przypisz pozycję do systemu RPG.")

            vtt_name = vtt_platform.get_text().strip() if vtt_enabled.get_active() else ""
            if vtt_enabled.get_active() and not vtt_name:
                raise ValueError("Wpisz nazwę platformy VTT.")
            selling = collection_status.text() in {"Na sprzedaż", "Sprzedane"}
            selected_supplement_types = [
                label for label, check in supplement_checks if check.get_active()
            ]
            return {
                "nazwa": name.get_text(),
                "typ": item_type.text(),
                "system_gry_id": selected_game_system_id,
                "system_glowny_id": parent_id,
                "wydawca_id": publisher.identifier(),
                "jezyk": language.text(),
                "typ_suplementu": (
                    " | ".join(selected_supplement_types)
                    if item_type.text() == "Suplement"
                    else ""
                ),
                "status_gra": game_status.text(),
                "status_kolekcja": collection_status.text(),
                "fizyczny": physical.get_active(),
                "pdf": pdf.get_active(),
                "vtt": vtt_name,
                "cena_fiz": price_physical.get_text() if physical.get_active() else None,
                "cena_pdf": price_pdf.get_text() if pdf.get_active() else None,
                "cena_vtt": price_vtt.get_text() if vtt_enabled.get_active() else None,
                "cena_zakupu": purchase_price.get_text(),
                "waluta_zakupu": currency.get_text(),
                "cena_sprzedazy": sale_price.get_text() if selling else None,
                "waluta_sprzedazy": sale_currency.get_text() if selling else None,
                "rok_wydania": year.get_text(),
                "isbn": isbn.get_text(),
                "system_glowny_nazwa_custom": (
                    record.get("system_glowny_nazwa_custom") if record else None
                ),
            }

        def persist(payload: dict[str, Any]) -> None:
            try:
                self.repository.save_system(
                    payload,
                    int(record["id"]) if record else None,
                )
                dialog.close()
                self.refresh()
                self.notify_data_changed()
            except Exception as exc:
                info(dialog, "Błąd zapisu", str(exc), error=True)

        def save() -> None:
            try:
                payload = build_payload()
            except Exception as exc:
                info(dialog, "Błąd zapisu", str(exc), error=True)
                return

            isbn_value = str(payload.get("isbn") or "").strip()
            if isbn_value and not is_valid_isbn(isbn_value):
                confirm(
                    dialog,
                    "Nieprawidłowy numer ISBN",
                    "Numer ISBN ma nieprawidłowy format lub sumę kontrolną. "
                    "Możesz zapisać pozycję mimo ostrzeżenia.",
                    lambda: persist(payload),
                    confirm_label="Zapisz mimo to",
                    destructive=False,
                )
                return
            persist(payload)

        dialog.add_buttons(save)
        dialog.present()

        if normalize_isbn(isbn.get_text()):
            def auto_lookup() -> bool:
                if dialog.get_visible():
                    start_isbn_lookup()
                return False

            GLib.idle_add(auto_lookup)
