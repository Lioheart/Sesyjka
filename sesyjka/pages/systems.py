from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
import re
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..dialogs import ModalWindow, confirm, info, make_entry
from ..repository import Repository
from ..widgets import Choice, ChoiceDropDown, FormGrid, TextDropDown
from .base import CrudPage


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
                ("Nadrzędny", "system_glowny_nazwa"),
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

    @staticmethod
    def _collection_status_css(status: Any) -> str:
        normalized = str(status or "W kolekcji").strip().casefold()
        return {
            "w kolekcji": "status-collection-owned",
            "na sprzedaż": "status-collection-for-sale",
            "sprzedane": "status-collection-sold",
            "nieposiadane": "status-collection-not-owned",
            "do kupienia": "status-collection-wishlist",
            "pożyczone": "status-collection-loaned",
        }.get(normalized, "status-collection-not-owned")

    @classmethod
    def _group_collection_status_css(cls, records: list[dict[str, Any]]) -> str:
        statuses = {
            str(item.get("status_kolekcja") or "W kolekcji").strip().casefold()
            for item in records
        }
        if not statuses:
            return "status-collection-not-owned"
        if len(statuses) == 1:
            return cls._collection_status_css(next(iter(statuses)))
        return "status-collection-mixed"

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
            child["_row_css_class"] = self._collection_status_css(record.get("status_kolekcja"))
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
                    "_row_css_class": self._group_collection_status_css(game_records),
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
                    "_row_css_class": self._group_collection_status_css(records),
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
                    "_row_css_class": self._group_collection_status_css(orphaned),
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
            height=430,
        )
        form = FormGrid()
        name = make_entry(record.get("nazwa") if record else "", "Nazwa systemu gry")
        publisher_row, publisher = self._publisher_selector(
            dialog,
            record.get("wydawca_id") if record else None,
        )
        language = make_entry(record.get("jezyk") if record else "", "Język")
        notes = Gtk.TextView()
        notes.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        notes.set_size_request(-1, 100)
        if record and record.get("notatki"):
            notes.get_buffer().set_text(str(record["notatki"]))
        form.add_row("Nazwa *", name)
        form.add_row("Wydawca", publisher_row)
        form.add_row("Język", language)
        form.add_row("Notatki", notes)
        dialog.add_scrolled_content(form)

        def save() -> None:
            buffer = notes.get_buffer()
            text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
            try:
                self.repository.save_game_system(
                    {
                        "nazwa": name.get_text(),
                        "wydawca_id": publisher.identifier(),
                        "jezyk": language.get_text(),
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
            width=720,
            height=820,
        )
        form = FormGrid()
        name = make_entry(record.get("nazwa") if record else "", "Nazwa pozycji")
        selected_type = str(record.get("typ") or "Podręcznik Główny") if record else "Podręcznik Główny"
        item_type = TextDropDown(
            ["Podręcznik Główny", "Suplement", "Przygoda", "Dodatek", "Inne"],
            selected_type,
        )
        game_choices = [
            Choice(None, "Brak"),
            *[Choice(int(row["id"]), str(row["nazwa"])) for row in self.repository.game_systems()],
        ]
        game_system = ChoiceDropDown(game_choices, record.get("system_gry_id") if record else None)

        main_books = [
            row
            for row in self.repository.systems()
            if str(row.get("typ") or "").casefold() == "podręcznik główny".casefold()
            and (record is None or int(row["id"]) != int(record["id"]))
        ]
        parent_choices = [
            Choice(None, "Brak"),
            *[
                Choice(int(row["id"]), f"{row.get('system_gry_nazwa') or 'Bez systemu'} - {row['nazwa']}")
                for row in main_books
            ],
        ]
        parent_book = ChoiceDropDown(parent_choices, record.get("system_glowny_id") if record else None)
        main_book_map = {int(row["id"]): row for row in main_books}

        publisher_row, publisher = self._publisher_selector(
            dialog,
            record.get("wydawca_id") if record else None,
        )
        language = make_entry(record.get("jezyk") if record else "", "Język")

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
        form.add_row("Podręcznik nadrzędny", parent_book)
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
        dialog.add_scrolled_content(form)

        def parse_price(entry: Gtk.Entry) -> float:
            text = entry.get_text().strip().replace(",", ".")
            if not text:
                return 0.0
            try:
                return max(float(text), 0.0)
            except ValueError:
                return 0.0

        def update_total(*_args: object) -> None:
            total = 0.0
            if physical.get_active():
                total += parse_price(price_physical)
            if pdf.get_active():
                total += parse_price(price_pdf)
            if vtt_enabled.get_active():
                total += parse_price(price_vtt)
            purchase_price.set_text(f"{total:.2f}")

        def update_visibility(*_args: object) -> None:
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
        for entry in (price_physical, price_pdf, price_vtt):
            entry.connect("changed", update_total)
        update_visibility()

        def save() -> None:
            try:
                parent_id = parent_book.identifier()
                selected_game_system_id = game_system.identifier()
                if parent_id is not None:
                    parent = main_book_map.get(parent_id)
                    if parent and parent.get("system_gry_id") is not None:
                        selected_game_system_id = int(parent["system_gry_id"])
                if selected_game_system_id is None:
                    raise ValueError("Przypisz pozycję do systemu RPG.")

                vtt_name = vtt_platform.get_text().strip() if vtt_enabled.get_active() else ""
                if vtt_enabled.get_active() and not vtt_name:
                    raise ValueError("Wpisz nazwę platformy VTT.")
                selling = collection_status.text() in {"Na sprzedaż", "Sprzedane"}
                selected_supplement_types = [
                    label for label, check in supplement_checks if check.get_active()
                ]
                self.repository.save_system(
                    {
                        "nazwa": name.get_text(),
                        "typ": item_type.text(),
                        "system_gry_id": selected_game_system_id,
                        "system_glowny_id": parent_id,
                        "wydawca_id": publisher.identifier(),
                        "jezyk": language.get_text(),
                        "typ_suplementu": (
                            "; ".join(selected_supplement_types)
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
                        "system_glowny_nazwa_custom": record.get("system_glowny_nazwa_custom") if record else None,
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
